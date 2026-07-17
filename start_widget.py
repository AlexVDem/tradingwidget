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

# ---------------------------------------------------------------------------
# Single source of truth for all default configuration values.
# Used by both load_config() (fallback values) and ensure_files_exist()
# (initial file generation), so defaults are never out of sync.
# ---------------------------------------------------------------------------
DEFAULT_CONFIG = {
    "widget_width": 1800,
    "position_x": 150,
    "position_y": 50,
    "compact_mode": True,
    "dark_theme": True,
    "always_on_top": False,
    "enable_console_logs": False,
    "open_target": "window",
    "show_in_system_tray": True,
    "start_minimized": False,
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

class SettingsWindow(Gtk.Window):
    def __init__(self, parent_widget):
        Gtk.Window.__init__(self, title="TradingView Ticker Settings")
        self.parent_widget = parent_widget
        self.set_default_size(520, 680)
        self.set_position(Gtk.WindowPosition.CENTER)
        
        # Hide this window from the dock and taskbar
        self.set_skip_taskbar_hint(True)
        
        icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart.png")
        if os.path.exists(icon_path):
            self.set_icon_from_file(icon_path)
            
        context = WebKit2.WebContext.get_default()
        self.webview = WebKit2.WebView.new_with_context(context)
        
        # Connect to script messages
        manager = self.webview.get_user_content_manager()
        manager.register_script_message_handler("save_config")
        manager.register_script_message_handler("cancel_settings")
        manager.connect("script-message-received::save_config", self.on_save_config)
        manager.connect("script-message-received::cancel_settings", self.on_cancel_settings)
        self.webview.connect("load-changed", self.on_load_changed)
        
        self.add(self.webview)
        self.show_all()
        
        settings_html_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings.html")
        self.webview.load_uri(f"file://{settings_html_path}")
        
    def on_load_changed(self, webview, event):
        if event == WebKit2.LoadEvent.FINISHED:
            # Prepare configuration data
            config_data = {
                "widget_width": self.parent_widget.widget_width,
                "position_x": self.parent_widget.position_x,
                "position_y": self.parent_widget.position_y,
                "compact_mode": self.parent_widget.compact_mode,
                "dark_theme": self.parent_widget.dark_theme,
                "always_on_top": getattr(self.parent_widget, 'always_on_top', False),
                "hover_pause": self.parent_widget.hover_pause,
                "show_in_system_tray": self.parent_widget.show_in_system_tray,
                "start_minimized": self.parent_widget.start_minimized,
                "enable_console_logs": self.parent_widget.enable_console_logs,
                "open_target": self.parent_widget.open_target,
                "symbols": self.parent_widget.symbols
            }
            json_str = json.dumps(config_data)
            js_code = f"initSettings({json_str});"
            try:
                # Modern WebKit2 API (prevents DeprecationWarning)
                self.webview.evaluate_javascript(js_code, -1, None, None, None, None, None)
            except (AttributeError, TypeError):
                # Fallback for older WebKit2 versions
                self.webview.run_javascript(js_code, None, None, None)
            
    def on_cancel_settings(self, user_content_manager, js_result):
        self.destroy()
        
    def on_save_config(self, user_content_manager, js_result):
        try:
            value = js_result.get_js_value()
            if value.is_string():
                cfg_json = value.to_string()
                new_cfg = json.loads(cfg_json)
                self.parent_widget.apply_new_config(new_cfg)
                self.destroy()
        except Exception as e:
            print(f"Error parsing saved config: {e}")

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
        
        # Window setup: undecorated, skip taskbar and pager
        self.set_type_hint(Gdk.WindowTypeHint.UTILITY)
        
        # Apply always-on-top or always-below layer settings
        if getattr(self, 'always_on_top', False):
            self.set_keep_above(True)
            self.set_keep_below(False)
        else:
            self.set_keep_below(True)
            self.set_keep_above(False)
            
        self.set_decorated(False)
        self.set_app_paintable(True)
        self.set_skip_taskbar_hint(True)
        self.set_skip_pager_hint(True)

        # Set default size using config parameters
        window_height = 69 if getattr(self, 'compact_mode', True) else 97
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

        # Handle start mode (minimized to tray vs visible window)
        self.widget_visible = True
        if getattr(self, 'start_minimized', False) and getattr(self, 'show_in_system_tray', True):
            self.hide()
            self.widget_visible = False
            self.update_tray_menu_label()

    def setup_system_tray(self):
        if getattr(self, 'show_in_system_tray', True) and HAS_APPINDICATOR:
            icon_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "chart.png")
            
            menu = Gtk.Menu()
            
            # Toggle visibility item
            self.tray_toggle_item = Gtk.MenuItem(label="Hide" if getattr(self, 'widget_visible', True) else "Show")
            self.tray_toggle_item.connect("activate", self.on_toggle_visibility_clicked)
            menu.append(self.tray_toggle_item)
            
            # Separator for toggle
            sep_toggle = Gtk.SeparatorMenuItem()
            menu.append(sep_toggle)
            
            # Settings item
            settings_item = Gtk.MenuItem(label="Settings")
            settings_item.connect("activate", self.on_open_settings)
            menu.append(settings_item)
            
            # Separator
            sep = Gtk.SeparatorMenuItem()
            menu.append(sep)
            
            # Close item
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
            
            # Hide option (only if tray icon is enabled so user doesn't lose the widget)
            if getattr(self, 'show_in_system_tray', True):
                hide_item = Gtk.MenuItem(label="Hide")
                hide_item.connect("activate", lambda w: self.set_widget_visible(False))
                menu.append(hide_item)
                
                # Separator
                sep_hide = Gtk.SeparatorMenuItem()
                menu.append(sep_hide)
            
            # Settings item
            settings_item = Gtk.MenuItem(label="Settings")
            settings_item.connect("activate", self.on_open_settings)
            menu.append(settings_item)
            
            # Separator
            sep = Gtk.SeparatorMenuItem()
            menu.append(sep)
            
            # Close item
            item = Gtk.MenuItem(label="Close Widget")
            item.connect("activate", lambda w: Gtk.main_quit())
            menu.append(item)
            
            menu.show_all()
            menu.popup(None, None, None, None, event.button, event.time)
            return True # Prevent webkit default context menu
        return False

    def on_open_settings(self, widget):
        if not hasattr(self, 'settings_win') or self.settings_win is None:
            self.settings_win = SettingsWindow(self)
            self.settings_win.connect("destroy", self.on_settings_closed)
        else:
            self.settings_win.present()
            
    def on_settings_closed(self, widget):
        self.settings_win = None

    def on_toggle_visibility_clicked(self, widget):
        self.set_widget_visible(not getattr(self, 'widget_visible', True))

    def set_widget_visible(self, visible):
        self.widget_visible = visible
        if visible:
            self.show()
        else:
            self.hide()
        self.update_tray_menu_label()

    def update_tray_menu_label(self):
        if hasattr(self, 'tray_toggle_item') and self.tray_toggle_item:
            self.tray_toggle_item.set_label("Hide" if getattr(self, 'widget_visible', True) else "Show")

    def apply_new_config(self, new_cfg):
        # 1. Update instance variables
        self.widget_width = new_cfg.get("widget_width", self.widget_width)
        self.position_x = new_cfg.get("position_x", self.position_x)
        self.position_y = new_cfg.get("position_y", self.position_y)
        self.compact_mode = new_cfg.get("compact_mode", self.compact_mode)
        self.dark_theme = new_cfg.get("dark_theme", self.dark_theme)
        self.always_on_top = new_cfg.get("always_on_top", getattr(self, 'always_on_top', False))
        self.hover_pause = new_cfg.get("hover_pause", self.hover_pause)
        self.show_in_system_tray = new_cfg.get("show_in_system_tray", self.show_in_system_tray)
        self.start_minimized = new_cfg.get("start_minimized", getattr(self, 'start_minimized', False))
        self.symbols = new_cfg.get("symbols", self.symbols)
        
        # Apply layer settings immediately on save
        if self.always_on_top:
            self.set_keep_above(True)
            self.set_keep_below(False)
        else:
            self.set_keep_below(True)
            self.set_keep_above(False)
        
        # 2. Save config to file
        try:
            with open(self.config_path, "w", encoding="utf-8") as f:
                json.dump(new_cfg, f, indent=4)
            print("Saved updated configuration to widget_config.json")
        except Exception as e:
            print(f"Failed to write configuration: {e}")
            
        # 3. Regenerate files (ticker.html)
        self.ensure_files_exist()
        
        # 4. Resize and move widget window
        window_height = 69 if self.compact_mode else 97
        self.resize(self.widget_width, window_height)
        self.move(self.position_x, self.position_y)
        
        # 5. Dynamic tray icon state
        if self.show_in_system_tray:
            if not hasattr(self, 'tray'):
                self.setup_system_tray()
        else:
            if hasattr(self, 'tray'):
                self.tray.set_status(AppIndicator3.IndicatorStatus.PASSIVE)
                del self.tray
                
        # 6. Re-configure WebKit UserScript for hover_pause and reload WebView
        manager = self.webview.get_user_content_manager()
        manager.remove_all_scripts()
        if not self.hover_pause:
            hover_fix_js = """
(function() {
    var HOVER_EVENTS = {
        mouseenter: 1, mouseleave: 1, mouseover: 1, mouseout: 1,
        pointerenter: 1, pointerleave: 1, pointerover: 1, pointerout: 1
    };
    var _addEventListener = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function(type, listener, options) {
        if (HOVER_EVENTS[type]) {
            return _addEventListener.call(this, type, function(){}, options);
        }
        return _addEventListener.call(this, type, listener, options);
    };
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

        current_dir = os.path.dirname(os.path.realpath(__file__))
        timestamp = int(time.time())
        item_size = "compact" if self.compact_mode else "normal"
        color_theme = "dark" if self.dark_theme else "light"
        hover_pause_val = "1" if self.hover_pause else "0"
        self.webview.load_uri(f"file://{os.path.join(current_dir, 'ticker.html')}?size={item_size}&theme={color_theme}&hover_pause={hover_pause_val}&t={timestamp}")



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
        divisor = 69.0 if getattr(self, 'compact_mode', True) else 97.0
        target_zoom = allocation.height / divisor
        
        # Limit the zoom range to sensible boundaries (e.g., between 0.5 and 5.0)
        clamped_zoom = max(0.5, min(target_zoom, 5.0))
        
        # Only set if the zoom level has actually changed to avoid a render loop
        if abs(self.webview.get_zoom_level() - clamped_zoom) > 0.01:
            self.webview.set_zoom_level(clamped_zoom)

    def ensure_files_exist(self):
        # ------------------------------------------------------------------
        # Auto-create widget_config.json if not present.
        # Uses the module-level DEFAULT_CONFIG so defaults are always in sync.
        # ------------------------------------------------------------------
        if not os.path.exists(self.config_path):
            try:
                with open(self.config_path, "w", encoding="utf-8") as f:
                    json.dump(DEFAULT_CONFIG, f, indent=4)
                print("Created default widget_config.json")
            except Exception as e:
                print(f"Failed to create default config: {e}")

        # ------------------------------------------------------------------
        # Auto-create settings.html if not present.
        # Default values shown in the form come directly from DEFAULT_CONFIG
        # so the UI always matches the config file defaults.
        # ------------------------------------------------------------------
        settings_html_path = os.path.join(os.path.dirname(os.path.realpath(__file__)), "settings.html")
        if not os.path.exists(settings_html_path):
            self._write_settings_html(settings_html_path)
        
        # Build default ticker.html
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
        """Load configuration from file, using DEFAULT_CONFIG values as fallback."""
        # Set instance attributes from the single source of truth
        for key, value in DEFAULT_CONFIG.items():
            setattr(self, key, value)

        if os.path.exists(self.config_path):
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    cfg = json.load(f)
                    self.widget_width = cfg.get("widget_width", self.widget_width)
                    self.position_x = cfg.get("position_x", self.position_x)
                    self.position_y = cfg.get("position_y", self.position_y)
                    self.compact_mode = cfg.get("compact_mode", self.compact_mode)
                    self.dark_theme = cfg.get("dark_theme", self.dark_theme)
                    self.always_on_top = cfg.get("always_on_top", getattr(self, 'always_on_top', False))
                    self.enable_console_logs = cfg.get("enable_console_logs", self.enable_console_logs)
                    self.open_target = cfg.get("open_target", self.open_target)
                    self.show_in_system_tray = cfg.get("show_in_system_tray", self.show_in_system_tray)
                    self.start_minimized = cfg.get("start_minimized", self.start_minimized)
                    self.hover_pause = cfg.get("hover_pause", self.hover_pause)
                    self.symbols = cfg.get("symbols", self.symbols)
            except Exception as e:
                print(f"Error reading configuration file: {e}")

    def _write_settings_html(self, path):
        """Generate settings.html with default values injected from DEFAULT_CONFIG.

        The HTML is self-contained — when loaded fresh (without Python calling
        initSettings), the form fields are pre-populated with DEFAULT_CONFIG
        values via an inline <script> block, so the user always sees sensible
        defaults even if something goes wrong on the Python side.
        """
        # Build a JSON-safe representation of the default symbols list
        default_symbols_json = json.dumps(DEFAULT_CONFIG["symbols"])
        default_cfg_json = json.dumps({
            "widget_width":       DEFAULT_CONFIG["widget_width"],
            "position_x":         DEFAULT_CONFIG["position_x"],
            "position_y":         DEFAULT_CONFIG["position_y"],
            "compact_mode":       DEFAULT_CONFIG["compact_mode"],
            "dark_theme":         DEFAULT_CONFIG["dark_theme"],
            "always_on_top":      DEFAULT_CONFIG["always_on_top"],
            "hover_pause":        DEFAULT_CONFIG["hover_pause"],
            "show_in_system_tray":DEFAULT_CONFIG["show_in_system_tray"],
            "start_minimized":    DEFAULT_CONFIG["start_minimized"],
            "enable_console_logs":DEFAULT_CONFIG["enable_console_logs"],
            "open_target":        DEFAULT_CONFIG["open_target"],
            "symbols":            DEFAULT_CONFIG["symbols"],
        })

        # Read the external settings.html template content from the module-level
        # string, then inject the defaults.  We keep all HTML in the external
        # settings.html file so this method only needs to write it once.
        settings_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>TradingView Widget Settings</title>
    <style>
        :root {{
            --bg-color: #131722;
            --container-bg: #1c2030;
            --input-bg: #2a2e3f;
            --text-color: #d1d4dc;
            --text-muted: #848e9c;
            --accent-color: #2962ff;
            --accent-hover: #1e4bd8;
            --danger-color: #f23645;
            --danger-hover: #cc202e;
            --border-radius: 8px;
            --border-color: #363c4e;
            --font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
        }}
        html, body {{
            height: 100%;
            margin: 0;
            padding: 0;
            background-color: var(--bg-color);
            color: var(--text-color);
            font-family: var(--font-family);
            font-size: 14px;
            user-select: none;
            overflow: hidden;
        }}
        h2 {{
            margin-top: 0;
            margin-bottom: 16px;
            font-size: 18px;
            font-weight: 600;
            border-bottom: 1px solid var(--border-color);
            padding-bottom: 10px;
            color: #ffffff;
            flex-shrink: 0;
        }}
        .settings-container {{
            display: flex;
            flex-direction: column;
            height: 100vh;
            box-sizing: border-box;
            max-width: 600px;
            margin: 0 auto;
            padding: 20px 20px 0 20px;
        }}
        .settings-content {{
            flex: 1;
            overflow-y: auto;
            padding-bottom: 20px;
            display: flex;
            flex-direction: column;
            gap: 16px;
        }}
        .settings-content::-webkit-scrollbar {{ width: 6px; }}
        .settings-content::-webkit-scrollbar-track {{ background: transparent; }}
        .settings-content::-webkit-scrollbar-thumb {{ background: var(--border-color); border-radius: 3px; }}
        .section-title {{
            font-size: 12px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.8px;
            color: var(--text-muted);
            margin-bottom: 8px;
        }}
        .settings-card {{
            background-color: var(--container-bg);
            border-radius: var(--border-radius);
            padding: 16px;
            border: 1px solid var(--border-color);
        }}
        .setting-row {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid rgba(255, 255, 255, 0.05);
        }}
        .setting-row:last-child {{ border-bottom: none; padding-bottom: 0; }}
        .setting-row:first-child {{ padding-top: 0; }}
        .setting-label {{ display: flex; flex-direction: column; gap: 4px; }}
        .setting-name {{ font-weight: 500; color: #ffffff; }}
        .setting-desc {{ font-size: 12px; color: var(--text-muted); }}
        input[type="number"], input[type="text"] {{
            background-color: var(--input-bg);
            border: 1px solid var(--border-color);
            color: #ffffff;
            padding: 8px 12px;
            border-radius: var(--border-radius);
            font-family: var(--font-family);
            font-size: 14px;
            outline: none;
            transition: border-color 0.2s;
            width: 100px;
            box-sizing: border-box;
        }}
        input[type="number"]:focus, input[type="text"]:focus {{ border-color: var(--accent-color); }}
        .switch {{ position: relative; display: inline-block; width: 44px; height: 24px; }}
        .switch input {{ opacity: 0; width: 0; height: 0; }}
        .slider {{
            position: absolute; cursor: pointer;
            top: 0; left: 0; right: 0; bottom: 0;
            background-color: var(--input-bg);
            transition: .3s; border-radius: 24px;
            border: 1px solid var(--border-color);
        }}
        .slider:before {{
            position: absolute; content: "";
            height: 16px; width: 16px;
            left: 3px; bottom: 3px;
            background-color: var(--text-color);
            transition: .3s; border-radius: 50%;
        }}
        input:checked + .slider {{ background-color: var(--accent-color); border-color: var(--accent-color); }}
        input:checked + .slider:before {{ transform: translateX(20px); background-color: #ffffff; }}
        .symbols-list {{
            display: flex; flex-direction: column; gap: 8px;
            max-height: 240px; overflow-y: auto;
            margin-bottom: 12px; padding-right: 4px;
        }}
        .symbols-list::-webkit-scrollbar {{ width: 6px; }}
        .symbols-list::-webkit-scrollbar-track {{ background: transparent; }}
        .symbols-list::-webkit-scrollbar-thumb {{ background: var(--border-color); border-radius: 3px; }}
        .symbol-item {{
            display: flex; gap: 8px; align-items: center;
            background-color: var(--input-bg);
            padding: 8px; border-radius: var(--border-radius);
            border: 1px solid var(--border-color);
        }}
        .symbol-item input[type="text"] {{ flex-grow: 1; width: 100%; }}
        .btn {{
            background-color: var(--input-bg);
            border: 1px solid var(--border-color);
            color: var(--text-color);
            padding: 8px 16px;
            border-radius: var(--border-radius);
            cursor: pointer;
            font-family: var(--font-family);
            font-size: 14px; font-weight: 500;
            display: flex; align-items: center; justify-content: center; gap: 6px;
            transition: background-color 0.2s, border-color 0.2s, color 0.2s;
            outline: none;
        }}
        .btn:hover {{ background-color: var(--border-color); color: #ffffff; }}
        .btn-accent {{ background-color: var(--accent-color); border-color: var(--accent-color); color: #ffffff; }}
        .btn-accent:hover {{ background-color: var(--accent-hover); border-color: var(--accent-hover); }}
        .btn-danger {{ color: var(--danger-color); }}
        .btn-danger:hover {{ background-color: var(--danger-color); border-color: var(--danger-color); color: #ffffff; }}
        .btn-icon {{ padding: 8px; width: 34px; height: 34px; box-sizing: border-box; }}
        .symbols-actions {{ display: flex; justify-content: flex-start; }}
        .footer-buttons {{
            display: flex; justify-content: flex-end; gap: 12px;
            border-top: 1px solid var(--border-color);
            padding: 16px 0 20px 0;
            background-color: var(--bg-color);
            flex-shrink: 0;
        }}
        .arrow-btn {{ font-size: 12px; }}
    </style>
</head>
<body>
    <div class="settings-container">
        <h2>TradingView Widget Settings</h2>

        <div class="settings-content">
            <!-- Size and Position -->
            <div class="section-title">Appearance &amp; Position</div>
            <div class="settings-card">
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Widget Width</span>
                        <span class="setting-desc">Ticker tape width on desktop (px)</span>
                    </div>
                    <input type="number" id="widget_width" min="200" max="7680" required>
                </div>
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Position X</span>
                        <span class="setting-desc">Horizontal offset from left edge (px)</span>
                    </div>
                    <input type="number" id="position_x" min="0" max="7680" required>
                </div>
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Position Y</span>
                        <span class="setting-desc">Vertical offset from top edge (px)</span>
                    </div>
                    <input type="number" id="position_y" min="0" max="4320" required>
                </div>
            </div>

            <!-- Toggles -->
            <div class="section-title">Display Options</div>
            <div class="settings-card">
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Compact Mode</span>
                        <span class="setting-desc">Reduced tape height (44px instead of 72px)</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="compact_mode">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Dark Theme</span>
                        <span class="setting-desc">Use TradingView dark theme</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="dark_theme">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Always on Top</span>
                        <span class="setting-desc">Keep the widget visible above all other windows</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="always_on_top">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">Pause on Hover</span>
                        <span class="setting-desc">Stop scrolling when cursor hovers over widget</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="hover_pause">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="setting-row">
                    <div class="setting-label">
                        <span class="setting-name">System Tray Icon</span>
                        <span class="setting-desc">Show widget icon in taskbar</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="show_in_system_tray">
                        <span class="slider"></span>
                    </label>
                </div>
                <div class="setting-row" id="start_minimized_row">
                    <div class="setting-label">
                        <span class="setting-name">Start Minimized to Tray</span>
                        <span class="setting-desc">Start the widget hidden on the desktop, only showing the tray icon</span>
                    </div>
                    <label class="switch">
                        <input type="checkbox" id="start_minimized">
                        <span class="slider"></span>
                    </label>
                </div>
            </div>

            <!-- Symbols List -->
            <div class="section-title">Ticker List (Symbols)</div>
            <div class="settings-card">
                <div class="symbols-list" id="symbols_container"></div>
                <div class="symbols-actions">
                    <button type="button" class="btn" id="btn_add_symbol">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><path d="M12 5v14M5 12h14"/></svg>
                        Add Ticker
                    </button>
                </div>
            </div>
        </div>

        <!-- Footer Buttons -->
        <div class="footer-buttons">
            <button type="button" class="btn" id="btn_cancel">Cancel</button>
            <button type="button" class="btn btn-accent" id="btn_save">Save</button>
        </div>
    </div>

    <script>
        // Default config values injected from Python at file-generation time.
        // initSettings() called by Python after page load will override these.
        const DEFAULT_VALUES = {default_cfg_json};

        let currentConfig = Object.assign({{}}, DEFAULT_VALUES);

        // Called by Python after the page finishes loading
        window.initSettings = function(configJson) {{
            try {{
                currentConfig = typeof configJson === 'string' ? JSON.parse(configJson) : configJson;
                populateForm(currentConfig);
            }} catch (e) {{
                console.error("Error initializing settings: " + e);
            }}
        }};

        const showTrayCheckbox = document.getElementById('show_in_system_tray');
        const startMinCheckbox = document.getElementById('start_minimized');
        const startMinRow = document.getElementById('start_minimized_row');

        function updateCheckboxDependencies() {{
            if (!showTrayCheckbox.checked) {{
                startMinCheckbox.checked = false;
                startMinCheckbox.disabled = true;
                startMinRow.style.opacity = '0.5';
            }} else {{
                startMinCheckbox.disabled = false;
                startMinRow.style.opacity = '1';
            }}
        }}

        showTrayCheckbox.addEventListener('change', updateCheckboxDependencies);

        function populateForm(cfg) {{
            document.getElementById('widget_width').value = cfg.widget_width || DEFAULT_VALUES.widget_width;
            document.getElementById('position_x').value   = cfg.position_x   || DEFAULT_VALUES.position_x;
            document.getElementById('position_y').value   = cfg.position_y   || DEFAULT_VALUES.position_y;
            document.getElementById('compact_mode').checked       = !!cfg.compact_mode;
            document.getElementById('dark_theme').checked         = !!cfg.dark_theme;
            document.getElementById('always_on_top').checked      = !!cfg.always_on_top;
            document.getElementById('hover_pause').checked        = !!cfg.hover_pause;
            document.getElementById('show_in_system_tray').checked = !!cfg.show_in_system_tray;
            document.getElementById('start_minimized').checked    = !!cfg.start_minimized;
            
            updateCheckboxDependencies();

            const container = document.getElementById('symbols_container');
            container.innerHTML = '';
            if (Array.isArray(cfg.symbols)) {{
                cfg.symbols.forEach(sym => {{ addSymbolRow(sym); }});
            }}
        }}

        // Pre-populate with defaults immediately on load (Python will override via initSettings)
        populateForm(DEFAULT_VALUES);

        function addSymbolRow(symbolText) {{
            const container = document.getElementById('symbols_container');
            const item = document.createElement('div');
            item.className = 'symbol-item';
            const input = document.createElement('input');
            input.type = 'text';
            input.placeholder = 'EXCHANGE:TICKER (e.g. NASDAQ:AAPL)';
            input.value = symbolText || '';
            item.appendChild(input);
            const btnUp = document.createElement('button');
            btnUp.type = 'button'; btnUp.className = 'btn btn-icon arrow-btn';
            btnUp.innerHTML = '▲'; btnUp.title = 'Move Up';
            btnUp.addEventListener('click', () => {{
                const prev = item.previousElementSibling;
                if (prev) {{ container.insertBefore(item, prev); }}
            }});
            item.appendChild(btnUp);
            const btnDown = document.createElement('button');
            btnDown.type = 'button'; btnDown.className = 'btn btn-icon arrow-btn';
            btnDown.innerHTML = '▼'; btnDown.title = 'Move Down';
            btnDown.addEventListener('click', () => {{
                const next = item.nextElementSibling;
                if (next) {{ container.insertBefore(next, item); }}
            }});
            item.appendChild(btnDown);
            const btnDel = document.createElement('button');
            btnDel.type = 'button'; btnDel.className = 'btn btn-icon btn-danger';
            btnDel.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M3 6h18M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2M10 11v6M14 11v6"/></svg>';
            btnDel.title = 'Delete';
            btnDel.addEventListener('click', () => {{ item.remove(); }});
            item.appendChild(btnDel);
            container.appendChild(item);
            container.scrollTop = container.scrollHeight;
        }}

        document.getElementById('btn_add_symbol').addEventListener('click', () => {{ addSymbolRow(''); }});

        document.getElementById('btn_cancel').addEventListener('click', () => {{
            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.cancel_settings) {{
                window.webkit.messageHandlers.cancel_settings.postMessage('');
            }}
        }});

        document.getElementById('btn_save').addEventListener('click', () => {{
            const width = parseInt(document.getElementById('widget_width').value, 10);
            const posX  = parseInt(document.getElementById('position_x').value, 10);
            const posY  = parseInt(document.getElementById('position_y').value, 10);
            if (isNaN(width) || width < 200) {{ alert("Please specify a valid width (minimum 200px)"); return; }}
            if (isNaN(posX)  || posX  < 0)   {{ alert("Please specify a valid X position"); return; }}
            if (isNaN(posY)  || posY  < 0)   {{ alert("Please specify a valid Y position"); return; }}
            const symbolInputs = document.querySelectorAll('.symbol-item input[type="text"]');
            const symbols = [];
            symbolInputs.forEach(inp => {{
                const val = inp.value.trim().toUpperCase();
                if (val) {{ symbols.push(val); }}
            }});
            if (symbols.length === 0) {{ alert("The ticker list must not be empty!"); return; }}
            const updatedConfig = {{
                widget_width:        width,
                position_x:          posX,
                position_y:          posY,
                compact_mode:        document.getElementById('compact_mode').checked,
                dark_theme:          document.getElementById('dark_theme').checked,
                always_on_top:       document.getElementById('always_on_top').checked,
                hover_pause:         document.getElementById('hover_pause').checked,
                show_in_system_tray: document.getElementById('show_in_system_tray').checked,
                start_minimized:     document.getElementById('start_minimized').checked,
                enable_console_logs: currentConfig.enable_console_logs || false,
                open_target:         currentConfig.open_target || "window",
                symbols:             symbols
            }};
            if (window.webkit && window.webkit.messageHandlers && window.webkit.messageHandlers.save_config) {{
                window.webkit.messageHandlers.save_config.postMessage(JSON.stringify(updatedConfig));
            }}
        }});
    </script>
</body>
</html>"""
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(settings_html)
            print("Created default settings.html")
        except Exception as e:
            print(f"Failed to create settings.html: {e}")

    def make_click_through(self, widget):
        window = widget.get_window()
        if window:
            # Create an empty input shape region to let mouse clicks pass through
            region = Gdk.cairo_region_create()
            window.input_shape_combine_region(region)

if __name__ == "__main__":
    win = DesktopWidget()
    Gtk.main()
