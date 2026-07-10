import os
import gi
import json
import time
import webbrowser
gi.require_version('Gtk', '3.0')
try:
    gi.require_version('WebKit2', '4.1')
except ValueError:
    gi.require_version('WebKit2', '4.0')

from gi.repository import Gtk, WebKit2, Gdk, GLib

class ChartWindow(Gtk.Window):
    def __init__(self, uri, title="TradingView Chart"):
        Gtk.Window.__init__(self, title=title)
        self.set_default_size(1200, 800)
        self.set_position(Gtk.WindowPosition.CENTER)
        
        self.webview = WebKit2.WebView()
        self.add(self.webview)
        self.webview.load_uri(uri)
        self.show_all()

class DesktopWidget(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)
        
        # Declare configuration and html paths
        self.config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "widget_config.json")
        self.html_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ticker.html")

        # Load configuration with fallback defaults
        self.load_config()

        # Check and auto-create files if missing
        self.ensure_files_exist()
        
        # Connect window destroy signal to stop the Gtk main loop
        self.connect("destroy", Gtk.main_quit)
        
        # Window setup: undecorated, always below, skip taskbar and pager
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        self.set_keep_below(True)
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        # Set default size using config parameters
        window_height = 76 if getattr(self, 'item_size', 'compact') == 'compact' else 104
        self.set_default_size(self.widget_width, window_height)
        # Position on screen (x, y) from config
        self.move(self.position_x, self.position_y)

        # RGBA visual for transparency support
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)

        # Disable cache via WebContext
        context = WebKit2.WebContext.get_default()
        context.set_cache_model(WebKit2.CacheModel.DOCUMENT_VIEWER) # Minimal caching
        context.clear_cache() # Clear any existing cache
        
        # Configure webview settings based on configuration parameter
        settings = WebKit2.Settings()
        settings.set_enable_write_console_messages_to_stdout(getattr(self, 'enable_console_logs', False))
        
        self.webview = WebKit2.WebView.new_with_context(context)
        self.webview.set_settings(settings)
        self.webview.set_background_color(Gdk.RGBA(0, 0, 0, 0)) # Transparent background
        
        # Load HTML with cache-busting timestamp and item_size parameter
        current_dir = os.path.dirname(os.path.realpath(__file__))
        timestamp = int(time.time())
        self.webview.load_uri(f"file://{os.path.join(current_dir, 'ticker.html')}?size={self.item_size}&t={timestamp}")
        
        self.add(self.webview)
        self.show_all()

        # Connect to decide-policy to open clicked links in default system browser
        self.webview.connect("decide-policy", self.on_decide_policy)

        # Connect to create signal to handle links opening in new windows (like target="_blank")
        self.webview.connect("create", self.on_create_webview)

        # Temporarily disable click-through for testing click events
        # self.connect("map", self.make_click_through)
        
        # Connect to size-allocate signal to dynamically scale zoom based on window height
        self.connect("size-allocate", self.on_size_allocate)

    def on_create_webview(self, webview, navigation_action):
        # Extract target URI from navigation action
        request = navigation_action.get_request()
        uri = request.get_uri()
        if getattr(self, 'enable_console_logs', False):
            print(f"[CREATE INTERCEPTED] New window request for: {uri}")
        
        # If it's a TradingView symbol page, extract and print symbol details
        if "tradingview.com" in uri:
            parts = uri.split('/symbols/')
            symbol = "Chart"
            if len(parts) > 1:
                symbol = parts[1].split('/')[0]
                if getattr(self, 'enable_console_logs', False):
                    print(f"[CREATE SYMBOL DETECTED]: {symbol}")
                    
            if getattr(self, 'open_target', 'browser') == 'window':
                if not hasattr(self, 'chart_windows'):
                    self.chart_windows = []
                # Keep a reference to prevent garbage collection of the new window
                new_chart_win = ChartWindow(uri, title=f"TradingView - {symbol}")
                self.chart_windows.append(new_chart_win)
            else:
                webbrowser.open(uri)
            
        # Return None to prevent WebKit from trying to open a new internal window
        return None

    def on_decide_policy(self, webview, decision, decision_type):
        if decision_type == WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION or decision_type == WebKit2.PolicyDecisionType.NAVIGATION_ACTION:
            nav_decision = decision
            request = nav_decision.get_navigation_action().get_request()
            uri = request.get_uri()
            
            # Intercept any clicks on symbol page links
            if "tradingview.com" in uri:
                if getattr(self, 'enable_console_logs', False):
                    print(f"[POLICY INTERCEPTED] Opened URL: {uri}")
                # Extract symbol from URL for verification
                parts = uri.split('/symbols/')
                symbol = "Chart"
                if len(parts) > 1:
                    symbol = parts[1].split('/')[0]
                    if getattr(self, 'enable_console_logs', False):
                        print(f"[POLICED SYMBOL DETECTED]: {symbol}")
                
                if getattr(self, 'open_target', 'browser') == 'window':
                    if not hasattr(self, 'chart_windows'):
                        self.chart_windows = []
                    new_chart_win = ChartWindow(uri, title=f"TradingView - {symbol}")
                    self.chart_windows.append(new_chart_win)
                else:
                    webbrowser.open(uri)
                decision.ignore()
                return True
                
        decision.use()
        return True

    def on_size_allocate(self, widget, allocation):
        # The base height of the TradingView ticker is ~44px (compact) or ~72px (normal).
        # We increase the divisor to give more vertical margin/padding.
        divisor = 58.0 if getattr(self, 'item_size', 'compact') == 'compact' else 86.0
        target_zoom = allocation.height / divisor
        
        # Limit the zoom range to sensible boundaries (e.g., between 0.5 and 5.0)
        clamped_zoom = max(0.5, min(target_zoom, 5.0))
        
        # Only set if the zoom level has actually changed to avoid a render loop
        if abs(self.webview.get_zoom_level() - clamped_zoom) > 0.01:
            self.webview.set_zoom_level(clamped_zoom)

    def ensure_files_exist(self):
        # Default JSON config content
        default_config = {
            "widget_width": 1800,
            "position_x": 150,
            "position_y": 50,
            "item_size": "compact",
            "enable_console_logs": False,
            "open_target": "window",
            "symbols": [
                "FOREXCOM:SPXUSD",
                "FOREXCOM:NSXUSD",
                "FOREXCOM:DJI",
                "BITSTAMP:BTCUSD",
                "BITSTAMP:ETHUSD",
                "CMCMARKETS:GOLD",
                "NASDAQ:GOOG",
                "NASDAQ:NVDA",
                "BYBIT:TRXUSDT.P"
            ]
        }
        
        # Default HTML content (fully restored style, reads size from URL query parameters synchronously)
        default_html = """<!DOCTYPE html>
<html>
<head>
    <style>
        body, html {
            margin: 0;
            padding: 0;
            width: 100%;
            height: 100%;
            overflow: hidden;
            background-color: transparent;
        }
        .widget-container {
            width: 100%;
            height: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
            overflow: hidden; /* Hide anything that overflows (clipped border) */
            position: relative;
        }
        tv-ticker-tape {
            width: 100%;
            height: {tape_height}; /* Fix the height dynamically */
            position: absolute;
            top: 50%;
            transform: translateY(-50%); /* Centered vertically */
        }
        /* Completely hide any copyright container or links generated by the widget */
        .tradingview-widget-copyright, 
        [class*="copyright"], 
        a[href*="tradingview.com"] {
            display: none !important;
            visibility: hidden !important;
            opacity: 0 !important;
            height: 0 !important;
            padding: 0 !important;
            margin: 0 !important;
        }
    </style>
</head>
<body>
    <div class="widget-container">
        <script>
            // Suppress the harmless ResizeObserver loop warning to keep the console clean
            window.addEventListener('error', function(e) {
                if (e.message && (e.message.includes('ResizeObserver') || e.message.includes('loop limit exceeded'))) {
                    e.stopImmediatePropagation();
                    e.preventDefault();
                }
            });
            window.onerror = function(message, source, lineno, colno, error) {
                if (message && (message.includes('ResizeObserver') || message.includes('loop limit exceeded'))) {
                    return true;
                }
                return false;
            };

            // Read item_size synchronously from URI query parameter (e.g. ?size=compact)
            const urlParams = new URLSearchParams(window.location.search);
            const itemSize = (urlParams.get('size') === 'compact') ? 'compact' : 'normal';
            
            const container = document.querySelector('.widget-container');
            
            // Create the script tag
            const script = document.createElement('script');
            script.type = 'module';
            script.src = 'https://widgets.tradingview-widget.com/w/en/tv-ticker-tape.js';
            script.async = true;
            document.head.appendChild(script);
            
            // Create the widget tag
            const widget = document.createElement('tv-ticker-tape');
            widget.setAttribute('symbols', '{symbols_string}');
            widget.setAttribute('item-size', itemSize);
            widget.setAttribute('color-theme', 'dark');
            widget.setAttribute('is-interactive', 'true');
            widget.setAttribute('show-symbol-logo', 'true');
            
            container.appendChild(widget);

        </script>
    </div>
</body>
</html>"""

        # Auto-create widget_config.json if not present
        if not os.path.exists(self.config_path):
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(default_config, f, indent=4)
                print("Created default widget_config.json")
            except Exception as e:
                print(f"Failed to create default config: {e}")
                
        # Always regenerate ticker.html to reflect current config
        symbols_csv = ",".join(self.symbols)
        tape_height = "44px" if getattr(self, 'item_size', 'compact') == 'compact' else "72px"
        formatted_html = default_html.replace("{symbols_string}", symbols_csv).replace("{tape_height}", tape_height)
        try:
            with open(self.html_path, "w", encoding="utf-8") as f:
                f.write(formatted_html)
            print("Regenerated ticker.html with current config")
        except Exception as e:
            print(f"Failed to generate html file: {e}")

    def load_config(self):
        # Default fallback values
        self.widget_width = 1800
        self.position_x = 150
        self.position_y = 50
        self.item_size = "compact"
        self.enable_console_logs = False
        self.open_target = "window"
        self.symbols = [
            "FOREXCOM:SPXUSD",
            "FOREXCOM:NSXUSD",
            "FOREXCOM:DJI",
            "BITSTAMP:BTCUSD",
            "BITSTAMP:ETHUSD",
            "CMCMARKETS:GOLD",
            "NASDAQ:GOOG",
            "NASDAQ:NVDA",
            "BYBIT:TRXUSDT.P"
        ]
        
        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.widget_width = cfg.get("widget_width", self.widget_width)
                    self.position_x = cfg.get("position_x", self.position_x)
                    self.position_y = cfg.get("position_y", self.position_y)
                    self.item_size = cfg.get("item_size", self.item_size)
                    self.enable_console_logs = cfg.get("enable_console_logs", self.enable_console_logs)
                    self.open_target = cfg.get("open_target", self.open_target)
                    self.symbols = cfg.get("symbols", self.symbols)
            except Exception as e:
                print(f"Error reading configuration file: {e}")

    def make_click_through(self, widget):
        window = widget.get_window()
        if window:
            # Create an empty input shape region to let mouse clicks pass through
            region = Gdk.cairo_region_create()
            window.input_shape_combine_region(region)

if __name__ == "__main__":
    win = DesktopWidget()
    Gtk.main()
