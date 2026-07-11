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

try:
    gi.require_version('AppIndicator3', '0.1')
    from gi.repository import AppIndicator3
    HAS_APPINDICATOR = True
except ValueError:
    HAS_APPINDICATOR = False

from gi.repository import Gtk, WebKit2, Gdk, GLib

class ChartWindow(Gtk.Window):
    def __init__(self, uri, title="TradingView Chart", parent_windows_list=None):
        Gtk.Window.__init__(self, title=title)
        self.set_default_size(1200, 800)
        self.set_position(Gtk.WindowPosition.CENTER)
        
        # Hide this window from the dock and taskbar completely
        self.set_skip_taskbar_hint(True)
        
        self.parent_windows_list = parent_windows_list
        self.connect("delete-event", self.on_delete_event)
        
        icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart.png")
        if os.path.exists(icon_path):
            self.set_icon_from_file(icon_path)
            
        self.webview = WebKit2.WebView()
        self.add(self.webview)
        self.webview.load_uri(uri)
        self.show_all()

    def on_delete_event(self, widget, event):
        # Instantly hide the window from screen and dock
        self.hide()
        self.set_skip_taskbar_hint(True)
        
        # Remove reference from parent so Python garbage collector can delete it
        if self.parent_windows_list is not None and self in self.parent_windows_list:
            self.parent_windows_list.remove(self)
            
        # Hard destroy WebKit and the window
        self.webview.destroy()
        self.destroy()
        
        # Return True to indicate we've handled the deletion entirely ourselves
        return True

class DesktopWidget(Gtk.Window):
    def __init__(self):
        Gtk.Window.__init__(self, type=Gtk.WindowType.TOPLEVEL)
        
        icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart.png")
        if os.path.exists(icon_path):
            self.set_icon_from_file(icon_path)
            
        # Declare configuration and html paths
        self.config_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "widget_config.json")
        self.html_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "ticker.html")

        # Load configuration with fallback defaults
        self.load_config()

        # Check and auto-create files if missing
        self.ensure_files_exist()

        self.setup_system_tray()
        
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
        window_height = 76 if getattr(self, 'compact_mode', True) else 104
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

        # If hover_pause is disabled, inject a script at document-start that:
        # 1. Intercepts addEventListener to silently drop hover-related handlers
        #    (works regardless of whether the widget uses CSS or JS for pause logic)
        # 2. Forces shadow roots to open mode so CSS injection also works as backup
        if not getattr(self, 'hover_pause', False):
            manager = self.webview.get_user_content_manager()
            hover_fix_js = """
(function() {
    // All hover-related event types to suppress
    var HOVER_EVENTS = {
        mouseenter: 1, mouseleave: 1, mouseover: 1, mouseout: 1,
        pointerenter: 1, pointerleave: 1, pointerover: 1, pointerout: 1
    };

    // Replace addEventListener so hover handlers are registered as no-ops.
    // Click / keyboard / other events are passed through unchanged.
    var _addEventListener = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, listener, options) {
        if (HOVER_EVENTS[type]) {
            return _addEventListener.call(this, type, function(){}, options);
        }
        return _addEventListener.call(this, type, listener, options);
    };

    // Also force shadow roots open so CSS injection in ticker.html can work too
    var _attachShadow = Element.prototype.attachShadow;
    Element.prototype.attachShadow = function(init) {
        return _attachShadow.call(this, Object.assign({}, init, {mode: 'open'}));
    };
})();
"""
            user_script = WebKit2.UserScript(
                hover_fix_js,
                WebKit2.UserContentInjectedFrames.ALL_FRAMES,
                WebKit2.UserScriptInjectionTime.START,
                None, None
            )
            manager.add_script(user_script)

        # Load HTML with cache-busting timestamp and parameters
        current_dir = os.path.dirname(os.path.realpath(__file__))
        timestamp = int(time.time())
        item_size = "compact" if getattr(self, 'compact_mode', True) else "normal"
        color_theme = "dark" if getattr(self, 'dark_theme', True) else "light"
        hover_pause = "1" if getattr(self, 'hover_pause', False) else "0"
        self.webview.load_uri(f"file://{os.path.join(current_dir, 'ticker.html')}?size={item_size}&theme={color_theme}&hover_pause={hover_pause}&t={timestamp}")
        
        self.add(self.webview)
        self.show_all()

        # Connect to decide-policy to open clicked links in default system browser
        self.webview.connect("decide-policy", self.on_decide_policy)

        # Connect to create signal to handle links opening in new windows (like target="_blank")
        self.webview.connect("create", self.on_create_webview)

        # Connect right click for context menu
        self.webview.connect("button-press-event", self.on_button_press)

        # Temporarily disable click-through for testing click events
        # self.connect("map", self.make_click_through)
        
        # Connect to size-allocate signal to dynamically scale zoom based on window height
        self.connect("size-allocate", self.on_size_allocate)

    def setup_system_tray(self):
        if getattr(self, 'show_in_system_tray', True) and HAS_APPINDICATOR:
            icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart.png")
            
            menu = Gtk.Menu()
            item = Gtk.MenuItem(label="Close Widget")
            item.connect("activate", lambda w: Gtk.main_quit())
            menu.append(item)
            menu.show_all()
            
            if os.path.exists(icon_path):
                self.tray = AppIndicator3.Indicator.new(
                    "tradingview-widget",
                    icon_path,
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
            else:
                self.tray = AppIndicator3.Indicator.new(
                    "tradingview-widget",
                    "application-default-icon",
                    AppIndicator3.IndicatorCategory.APPLICATION_STATUS)
            
            self.tray.set_status(AppIndicator3.IndicatorStatus.ACTIVE)
            self.tray.set_menu(menu)

    def on_button_press(self, widget, event):
        if event.type == Gdk.EventType.BUTTON_PRESS and event.button == 3:
            menu = Gtk.Menu()
            item = Gtk.MenuItem(label="Close Widget")
            item.connect("activate", lambda w: Gtk.main_quit())
            menu.append(item)
            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)
            return True # Prevent webkit default context menu
        return False

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
                # Pass the list so the window can remove itself on close
                new_chart_win = ChartWindow(uri, title=f"TradingView - {symbol}", parent_windows_list=self.chart_windows)
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
                    new_chart_win = ChartWindow(uri, title=f"TradingView - {symbol}", parent_windows_list=self.chart_windows)
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
            "compact_mode": True,
            "dark_theme": True,
            "enable_console_logs": False,
            "open_target": "window",
            "show_in_system_tray": True,
            "hover_pause": False,
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

            // Read parameters synchronously from URI query parameter
            const urlParams = new URLSearchParams(window.location.search);
            const itemSize = (urlParams.get('size') === 'compact') ? 'compact' : 'normal';
            const colorTheme = (urlParams.get('theme') === 'light') ? 'light' : 'dark';
            const hoverPause = urlParams.get('hover_pause') === '1'; // default false
            
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
            widget.setAttribute('theme', colorTheme);
            widget.setAttribute('is-interactive', 'true');
            widget.setAttribute('show-symbol-logo', 'true');
            
            container.appendChild(widget);

            // When hover_pause is disabled: inject CSS directly into the widget's
            // open shadow DOM to force animation-play-state: running at all times.
            // This keeps native clicks working — no overlay needed.
            if (!hoverPause) {
                let fixApplied = false;

                const applyHoverFix = () => {
                    if (fixApplied) return true;
                    const tvWidget = document.querySelector('tv-ticker-tape');
                    if (tvWidget && tvWidget.shadowRoot) {
                        const style = document.createElement('style');
                        style.id = 'hover-pause-override';
                        // Force all animations to keep running regardless of hover state
                        style.textContent = '*, *:hover, *:focus { animation-play-state: running !important; }';
                        tvWidget.shadowRoot.appendChild(style);
                        fixApplied = true;
                        return true;
                    }
                    return false;
                };

                // Try immediately, then poll until the shadow DOM is ready
                if (!applyHoverFix()) {
                    const interval = setInterval(() => {
                        if (applyHoverFix()) clearInterval(interval);
                    }, 150);
                    // Stop trying after 15 seconds
                    setTimeout(() => clearInterval(interval), 15000);
                }
            }

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
        tape_height = "44px" if getattr(self, 'compact_mode', True) else "72px"
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
        self.compact_mode = True
        self.dark_theme = True
        self.enable_console_logs = False
        self.open_target = "window"
        self.show_in_system_tray = True
        self.hover_pause = False
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
                    self.compact_mode = cfg.get("compact_mode", self.compact_mode)
                    self.dark_theme = cfg.get("dark_theme", self.dark_theme)
                    self.enable_console_logs = cfg.get("enable_console_logs", self.enable_console_logs)
                    self.open_target = cfg.get("open_target", self.open_target)
                    self.show_in_system_tray = cfg.get("show_in_system_tray", self.show_in_system_tray)
                    self.hover_pause = cfg.get("hover_pause", self.hover_pause)
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
