"""KatanaGlow settings window (GTK4). It only talks to the service over its control socket:
no hardware access, no keyboard access, no special privileges. Closing it leaves the lighting running."""
import copy
import sys
import time

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Gdk", "4.0")
from gi.repository import Gdk, GLib, Gtk

from . import client, config, gui_model as m

POLL_SECONDS = 2
EXTERNAL_CHANGE_GRACE = 2.0        # don't overwrite widgets right after the user touched one


class Window:
    def __init__(self, app):
        self.cfg = copy.deepcopy(config.DEFAULTS)
        self._loading = False
        self._last_edit = 0.0
        self.queue = m.PatchQueue(self._send, lambda ms, fn: GLib.timeout_add(ms, fn),
                                  GLib.source_remove, on_error=self._show_error)

        self.win = Gtk.ApplicationWindow(application=app, title="KatanaGlow")
        self.win.set_default_size(500, -1)
        root = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        for side in ("top", "bottom", "start", "end"):
            getattr(root, f"set_margin_{side}")(16)
        self.win.set_child(root)

        self.status = Gtk.Label(label="Connecting...", xalign=0.0)
        root.append(self.status)
        self.controls = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=14)
        root.append(self.controls)

        self._build_profiles()
        self._build_modes()
        self._build_zones()
        self._build_palette()
        self._build_base()
        self._build_sliders()
        self._build_balance()

        self.load_config()                  # show defaults until the service answers
        self.refresh(force=True)
        GLib.timeout_add_seconds(POLL_SECONDS, self._poll)

    # ---- building the window ---------------------------------------------
    def _heading(self, text):
        label = Gtk.Label(label=text, xalign=0.0)
        label.add_css_class("heading")
        return label

    def _section(self, title):
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        box.append(self._heading(title))
        self.controls.append(box)
        return box

    def _row(self, label, widget):
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        name = Gtk.Label(label=label, xalign=0.0)
        name.set_size_request(90, -1)
        row.append(name)
        row.append(widget)
        return row

    def _colour_button(self, hex_colour, on_change):
        dialog = Gtk.ColorDialog()
        dialog.set_with_alpha(False)
        button = Gtk.ColorDialogButton(dialog=dialog)
        self._set_button(button, hex_colour)
        button.connect("notify::rgba", lambda b, _p: on_change(self._button_hex(b)))
        return button

    @staticmethod
    def _set_button(button, hex_colour):
        rgba = Gdk.RGBA()
        rgba.red, rgba.green, rgba.blue = m.hex_to_floats(hex_colour)
        rgba.alpha = 1.0
        button.set_rgba(rgba)

    @staticmethod
    def _button_hex(button):
        c = button.get_rgba()
        return m.rgba_to_hex(c.red, c.green, c.blue)

    def _scale(self, lo, hi, step, digits, on_change):
        scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, lo, hi, step)
        scale.set_digits(digits)
        scale.set_draw_value(True)
        scale.set_value_pos(Gtk.PositionType.RIGHT)
        scale.set_hexpand(True)
        scale.connect("value-changed", lambda s: on_change(s.get_value()))
        return scale

    def _build_profiles(self):
        section = self._section("Profiles")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.profile_model = Gtk.StringList()
        self.profile_dropdown = Gtk.DropDown(model=self.profile_model)
        self.profile_dropdown.set_hexpand(True)
        self.apply_button, self.delete_button = Gtk.Button(label="Apply"), Gtk.Button(label="Delete")
        self.apply_button.connect("clicked", lambda _b: self._profile_apply())
        self.delete_button.connect("clicked", lambda _b: self._profile_delete())
        for widget in (self.profile_dropdown, self.apply_button, self.delete_button):
            row.append(widget)
        section.append(row)
        save_row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        self.profile_entry = Gtk.Entry()
        self.profile_entry.set_placeholder_text("Name for the current look")
        self.profile_entry.set_hexpand(True)
        save = Gtk.Button(label="Save current")
        save.connect("clicked", lambda _b: self._profile_save())
        self.profile_entry.connect("activate", lambda _e: self._profile_save())
        save_row.append(self.profile_entry)
        save_row.append(save)
        section.append(save_row)
        self._set_profile_names([])

    def _build_modes(self):
        self.mode_section = self._section("Mode")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=0)
        row.add_css_class("linked")
        self.mode_buttons, first = {}, None
        for key, label in m.MODES:
            button = Gtk.ToggleButton(label=label)
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.set_hexpand(True)
            button.connect("toggled", self._on_mode, key)
            row.append(button)
            self.mode_buttons[key] = button
        self.mode_section.append(row)

    def _build_zones(self):
        self.zones_section = self._section("Zone colours")
        row = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=12)
        row.set_homogeneous(True)
        self.zone_buttons = []
        for i, name in enumerate(m.ZONE_NAMES):
            column = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
            column.append(Gtk.Label(label=name))
            button = self._colour_button(self.cfg["zone_colours"][i],
                                         lambda h, i=i: self._zone_changed(i, h))
            column.append(button)
            row.append(column)
            self.zone_buttons.append(button)
        self.zones_section.append(row)

    def _build_palette(self):
        self.palette_section = self._section("Palette (colours are used in turn)")
        self.palette_flow = Gtk.FlowBox()
        self.palette_flow.set_selection_mode(Gtk.SelectionMode.NONE)
        self.palette_flow.set_max_children_per_line(8)
        self.palette_flow.set_homogeneous(True)
        self.palette_section.append(self.palette_flow)
        buttons = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=6)
        add, remove = Gtk.Button(label="Add colour"), Gtk.Button(label="Remove last")
        add.connect("clicked", lambda _b: self._palette_edit(m.add_colour))
        remove.connect("clicked", lambda _b: self._palette_edit(m.remove_colour))
        buttons.append(add)
        buttons.append(remove)
        self.palette_section.append(buttons)
        self._rebuild_palette()

    def _build_base(self):
        self.base_section = self._section("Ripple look")
        self.glow_scale = self._scale(0, 100, 1, 0, self._glow_changed)
        self.base_section.append(self._row("Resting glow", self.glow_scale))
        self.base_button = self._colour_button(self.cfg["base"], self._base_changed)
        self.base_section.append(self._row("Tint", self.base_button))
        self.punch_scale = self._scale(0.0, 1.0, 0.05, 2, self._punch_changed)
        self.base_section.append(self._row("Contrast", self.punch_scale))

    def _build_sliders(self):
        self.speed_section = self._section("Speed")
        self.speed_scale = self._scale(0.25, 4.0, 0.05, 2, self._speed_changed)
        self.speed_section.append(self.speed_scale)
        section = self._section("Brightness")
        self.brightness_scale = self._scale(0, 100, 1, 0, self._brightness_changed)
        section.append(self.brightness_scale)

    def _build_balance(self):
        expander = Gtk.Expander(label="Colour balance (advanced)")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6)
        self.gain_scales = []
        for name in ("Red", "Green", "Blue"):
            scale = self._scale(0.0, 1.0, 0.01, 2, self._gain_changed)
            box.append(self._row(name, scale))
            self.gain_scales.append(scale)
        expander.set_child(box)
        self.controls.append(expander)

    def _rebuild_palette(self):
        child = self.palette_flow.get_first_child()
        while child is not None:
            nxt = child.get_next_sibling()
            self.palette_flow.remove(child)
            child = nxt
        for idx, hex_colour in enumerate(self.cfg["palette"]):
            self.palette_flow.append(
                self._colour_button(hex_colour, lambda h, idx=idx: self._palette_changed(idx, h)))

    # ---- applying settings to the widgets --------------------------------
    def load_config(self):
        self._loading = True
        try:
            cfg = self.cfg
            self.mode_buttons[cfg["mode"]].set_active(True)
            for button, hex_colour in zip(self.zone_buttons, cfg["zone_colours"]):
                self._set_button(button, hex_colour)
            self._rebuild_palette()
            self._set_button(self.base_button, cfg["base"])
            self.glow_scale.set_value(m.hex_to_glow(cfg["base"]))
            self.punch_scale.set_value(cfg["punch"])
            self.speed_scale.set_value(cfg["speed"])
            self.brightness_scale.set_value(cfg["brightness"] * 100)
            for scale, value in zip(self.gain_scales, cfg["gain"]):
                scale.set_value(value)
            self._apply_visibility(cfg["mode"])
        finally:
            self._loading = False

    def _apply_visibility(self, mode):
        shown = m.visible_sections(mode)
        self.zones_section.set_visible("zones" in shown)
        self.palette_section.set_visible("palette" in shown)
        self.base_section.set_visible("base" in shown)
        self.speed_section.set_visible("speed" in shown)

    # ---- user edits ------------------------------------------------------
    def _edited(self, **patch):
        self._last_edit = time.monotonic()
        self.queue.add(**patch)

    def _on_mode(self, button, key):
        if self._loading or not button.get_active():
            return
        self.cfg["mode"] = key
        self._apply_visibility(key)
        self._edited(mode=key)

    def _zone_changed(self, i, hex_colour):
        if self._loading:
            return
        self.cfg["zone_colours"][i] = hex_colour
        self._edited(zone_colours=list(self.cfg["zone_colours"]))

    def _palette_changed(self, idx, hex_colour):
        if self._loading:
            return
        self.cfg["palette"][idx] = hex_colour
        self._edited(palette=list(self.cfg["palette"]))

    def _palette_edit(self, change):
        self.cfg["palette"] = change(self.cfg["palette"])
        self._loading = True
        try:
            self._rebuild_palette()
        finally:
            self._loading = False
        self._edited(palette=list(self.cfg["palette"]))

    def _base_changed(self, hex_colour):
        if self._loading:
            return
        self.cfg["base"] = hex_colour
        self._loading = True                       # keep the slider in step without re-sending
        try:
            self.glow_scale.set_value(m.hex_to_glow(hex_colour))
        finally:
            self._loading = False
        self._edited(base=hex_colour)

    def _glow_changed(self, value):
        if self._loading:
            return
        hex_colour = m.glow_to_hex(value)
        self.cfg["base"] = hex_colour
        self._loading = True                       # show the new grey on the tint button
        try:
            self._set_button(self.base_button, hex_colour)
        finally:
            self._loading = False
        self._edited(base=hex_colour)

    def _punch_changed(self, value):
        if not self._loading:
            self._edited(punch=round(value, 2))

    def _speed_changed(self, value):
        if not self._loading:
            self._edited(speed=round(value, 2))

    def _brightness_changed(self, value):
        if not self._loading:
            self._edited(brightness=round(value / 100, 3))

    def _gain_changed(self, _value):
        if not self._loading:
            self._edited(gain=[round(s.get_value(), 3) for s in self.gain_scales])

    # ---- profiles --------------------------------------------------------
    def _set_profile_names(self, names, select=None):
        self.profile_model.splice(0, self.profile_model.get_n_items(), list(names))
        if select in names:
            self.profile_dropdown.set_selected(list(names).index(select))
        have = bool(names)
        self.apply_button.set_sensitive(have)
        self.delete_button.set_sensitive(have)
        self.profile_dropdown.set_sensitive(have)

    def _selected_profile(self):
        index = self.profile_dropdown.get_selected()
        if index == Gtk.INVALID_LIST_POSITION or index >= self.profile_model.get_n_items():
            return None
        return self.profile_model.get_string(index)

    def _profile_call(self, action):
        """Run a profile request after sending any pending edits; report errors in the status line."""
        self.queue.flush_now()
        try:
            return action()
        except client.ClientError as e:
            self._show_error(str(e))
            return None

    def _profile_apply(self):
        name = self._selected_profile()
        reply = name and self._profile_call(lambda: client.load_profile(name))
        if reply:
            self.cfg = copy.deepcopy(reply["config"])
            self._last_edit = 0.0
            self.load_config()
            self.status.set_text(f"Applied profile {name}")

    def _profile_save(self):
        name = self.profile_entry.get_text().strip()
        if not name:
            self._show_error("type a name for the profile first")
            return
        names = self._profile_call(lambda: client.save_profile(name))
        if names is not None:
            self._set_profile_names(names, select=name)
            self.profile_entry.set_text("")
            self.status.set_text(f"Saved profile {name}")

    def _profile_delete(self):
        name = self._selected_profile()
        names = name and self._profile_call(lambda: client.delete_profile(name))
        if names is not None and name:
            self._set_profile_names(names)
            self.status.set_text(f"Deleted profile {name}")

    # ---- talking to the service ------------------------------------------
    def _send(self, patch):
        reply = client.set_config(patch)
        self.cfg = copy.deepcopy(reply["config"])

    def _show_error(self, message):
        self.status.set_text("Warning: " + message)

    def refresh(self, force=False):
        try:
            reply = client.get()
        except client.ClientError as e:
            self.controls.set_sensitive(False)
            self.status.set_text("Service not reachable: " + str(e))
            return
        self.controls.set_sensitive(True)
        st = reply["status"]
        text = "Controller connected" if st["device"] == "connected" else "Controller not connected"
        if reply["config"]["mode"] == "ripple":
            text += "  |  Keyboard: " + st["keyboard"]
        self.status.set_text(text)
        quiet = (not self.queue.pending) and time.monotonic() - self._last_edit > EXTERNAL_CHANGE_GRACE
        if force:
            try:
                self._set_profile_names(client.profiles(), select=self._selected_profile())
            except client.ClientError:
                pass
        if force or (quiet and reply["config"] != self.cfg):
            self.cfg = copy.deepcopy(reply["config"])
            self.load_config()

    def _poll(self):
        self.refresh()
        return True


def main():
    app = Gtk.Application(application_id="local.katanaglow.settings")
    windows = []

    def on_activate(application):
        if not windows:
            windows.append(Window(application))
        windows[0].win.present()

    app.connect("activate", on_activate)
    return app.run(sys.argv)


if __name__ == "__main__":
    sys.exit(main())
