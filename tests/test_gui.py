import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from katanaglow import client, config, gui_model as m


class ModelTests(unittest.TestCase):
    def test_glow_slider_maths(self):
        self.assertEqual(m.glow_to_hex(0), "000000")
        self.assertEqual(m.glow_to_hex(100), "FFFFFF")
        self.assertEqual(m.glow_to_hex(50), "404040")
        self.assertEqual(m.glow_to_hex(-5), "000000")
        self.assertEqual(m.glow_to_hex(500), "FFFFFF")
        for pct in (0, 10, 25, 50, 75, 100):
            self.assertAlmostEqual(m.hex_to_glow(m.glow_to_hex(pct)), pct, delta=3.5)
        self.assertGreater(m.hex_to_glow("FF0000"), 99)           # tinted base reports its brightest channel

    def test_colour_conversion(self):
        self.assertEqual(m.rgba_to_hex(1, 0, 0.5), "FF0080")
        self.assertEqual(m.rgba_to_hex(-1, 2, 0), "00FF00")
        self.assertEqual(m.hex_to_floats("FF8000"), (1.0, 128 / 255, 0.0))
        for h in ("000000", "FFFFFF", "A000FF", "12AB9C"):
            self.assertEqual(m.rgba_to_hex(*m.hex_to_floats(h)), h)

    def test_visible_sections(self):
        self.assertEqual(m.visible_sections("off"), set())
        self.assertEqual(m.visible_sections("static"), {"zones"})
        self.assertEqual(m.visible_sections("wave"), {"palette", "speed"})
        self.assertEqual(m.visible_sections("ripple"), {"palette", "speed", "base"})

    def test_palette_limits(self):
        p = ["FF0000"]
        self.assertEqual(m.remove_colour(p), p)
        for _ in range(20):
            p = m.add_colour(p)
        self.assertEqual(len(p), m.PALETTE_MAX)
        self.assertEqual(len(set(p)), len(p))
        self.assertEqual(len(m.remove_colour(p)), m.PALETTE_MAX - 1)

    def test_added_colours_pass_validation(self):
        cfg = config.merge(config.validate(config.DEFAULTS), {"palette": m.add_colour(["FF0000"])})
        self.assertEqual(len(cfg["palette"]), 2)


class QueueTests(unittest.TestCase):
    def setUp(self):
        self.sent, self.timers, self.errors = [], {}, []
        self.next_id = 0

        def schedule(ms, fn):
            self.next_id += 1
            self.timers[self.next_id] = fn
            return self.next_id

        self.q = m.PatchQueue(self.sent.append, schedule, lambda h: self.timers.pop(h, None),
                              on_error=self.errors.append)

    def fire(self):
        for fn in list(self.timers.values()):
            self.timers.clear()
            fn()

    def test_rapid_changes_merge_into_one_request(self):
        self.q.add(speed=1.0)
        self.q.add(speed=2.0, mode="wave")
        self.assertTrue(self.q.pending)
        self.assertEqual(len(self.timers), 1)
        self.fire()
        self.assertEqual(self.sent, [{"speed": 2.0, "mode": "wave"}])
        self.assertFalse(self.q.pending)

    def test_flush_now_cancels_timer(self):
        self.q.add(brightness=0.5)
        self.q.flush_now()
        self.assertEqual(self.sent, [{"brightness": 0.5}])
        self.assertEqual(self.timers, {})
        self.q.flush_now()
        self.assertEqual(len(self.sent), 1)

    def test_errors_are_reported_not_raised(self):
        def boom(_patch):
            raise client.ClientError("service not running")
        q = m.PatchQueue(boom, lambda ms, fn: 1, lambda h: None, on_error=self.errors.append)
        q.add(mode="off")
        q.flush_now()
        self.assertEqual(self.errors, ["service not running"])


class FakeRGBA:
    def __init__(self, r=0.0, g=0.0, b=0.0):
        self.red, self.green, self.blue, self.alpha = r, g, b, 1.0


class WindowLogicTests(unittest.TestCase):
    """Runs the real window code against a stand-in for GTK, so typos and logic slips show up.
    It cannot prove the GTK calls themselves are right; that needs a real display."""

    def setUp(self):
        fake_gi = mock.MagicMock()
        fake_gi.repository.Gdk.RGBA = FakeRGBA
        Gtk = fake_gi.repository.Gtk

        def fresh(**returns):                 # every widget must be its own object
            def make(*args, **kwargs):
                widget = mock.MagicMock()
                for name, value in returns.items():
                    getattr(widget, name).return_value = value
                return widget
            return make

        Gtk.INVALID_LIST_POSITION = 4294967295
        for name in ("Box", "ToggleButton", "ColorDialogButton", "ColorDialog", "Label", "Button", "Expander",
                     "Entry"):
            getattr(Gtk, name).side_effect = fresh()
        Gtk.DropDown.side_effect = fresh(get_selected=Gtk.INVALID_LIST_POSITION)   # nothing selected
        Gtk.StringList.side_effect = fresh(get_n_items=0)                          # empty list
        Gtk.FlowBox.side_effect = fresh(get_first_child=None)   # a real FlowBox runs out of children
        Gtk.Scale.new_with_range.side_effect = fresh()
        patches = mock.patch.dict(sys.modules, {"gi": fake_gi, "gi.repository": fake_gi.repository})
        patches.start()
        self.addCleanup(patches.stop)
        sys.modules.pop("katanaglow.gui", None)
        from katanaglow import gui
        self.addCleanup(lambda: sys.modules.pop("katanaglow.gui", None))
        self.gui = gui
        self.cfg = config.validate(config.DEFAULTS)
        self.sent = []

        def fake_get(path=None):
            return {"ok": True, "config": self.cfg, "status": {"device": "connected", "keyboard": "reading"}}

        self.profile_names = []

        def fake_profiles(path=None):
            return list(self.profile_names)

        def fake_save_profile(name, path=None):
            if name not in self.profile_names:
                self.profile_names = sorted(self.profile_names + [name])
            self.saved_profile = (name, dict(self.cfg))
            return list(self.profile_names)

        def fake_load_profile(name, path=None):
            self.loaded = name
            self.cfg = config.merge(self.cfg, {"mode": "static"})
            return {"ok": True, "config": self.cfg, "profiles": list(self.profile_names)}

        def fake_delete_profile(name, path=None):
            self.profile_names = [n for n in self.profile_names if n != name]
            return list(self.profile_names)

        def fake_set(patch, path=None):
            self.sent.append(patch)
            self.cfg = config.merge(self.cfg, patch)
            return {"ok": True, "config": self.cfg}

        patches2 = mock.patch.multiple(gui.client, get=fake_get, set_config=fake_set, profiles=fake_profiles,
                                       save_profile=fake_save_profile, load_profile=fake_load_profile,
                                       delete_profile=fake_delete_profile)
        patches2.start()
        self.addCleanup(patches2.stop)
        self.timers = []
        gui.GLib.timeout_add.side_effect = lambda ms, fn: self.timers.append(fn) or len(self.timers)
        self.w = gui.Window(mock.MagicMock())

    def flush(self):
        self.w.queue.flush_now()

    def test_loads_service_settings_without_sending_anything(self):
        self.assertEqual(self.sent, [])
        self.assertEqual(self.w.cfg["mode"], "ripple")
        self.w.mode_buttons["ripple"].set_active.assert_called_with(True)

    def test_mode_change_sends_patch_and_updates_visibility(self):
        btn = mock.MagicMock()
        btn.get_active.return_value = True
        self.w._on_mode(btn, "static")
        self.flush()
        self.assertEqual(self.sent, [{"mode": "static"}])
        self.w.zones_section.set_visible.assert_called_with(True)

    def test_inactive_toggle_is_ignored(self):
        btn = mock.MagicMock()
        btn.get_active.return_value = False
        self.w._on_mode(btn, "off")
        self.flush()
        self.assertEqual(self.sent, [])

    def test_zone_colour_edit_sends_whole_list(self):
        self.w._zone_changed(2, "123456")
        self.flush()
        self.assertEqual(self.sent[0]["zone_colours"][2], "123456")
        self.assertEqual(len(self.sent[0]["zone_colours"]), 4)

    def test_palette_add_remove_and_edit(self):
        before = len(self.cfg["palette"])
        self.w._palette_edit(m.add_colour)
        self.w._palette_edit(m.remove_colour)
        self.w._palette_edit(m.remove_colour)
        self.flush()
        self.assertEqual(len(self.sent), 1)                  # three edits merged
        self.assertEqual(len(self.sent[0]["palette"]), before - 1)
        self.w._palette_changed(0, "00FF00")
        self.flush()
        self.assertEqual(self.sent[1]["palette"][0], "00FF00")

    def test_sliders_send_scaled_values(self):
        self.w._brightness_changed(40)
        self.w._speed_changed(1.2345)
        for i, s in enumerate(self.w.gain_scales):
            s.get_value.return_value = [1.0, 0.5, 0.25][i]
        self.w._gain_changed(0)
        self.flush()
        self.assertEqual(self.sent, [{"brightness": 0.4, "speed": 1.23, "gain": [1.0, 0.5, 0.25]}])

    def test_glow_slider_sets_a_grey_and_updates_tint_button(self):
        self.w._glow_changed(50)
        self.flush()
        self.assertEqual(self.sent, [{"base": "404040"}])
        self.assertEqual(self.w.cfg["base"], "404040")
        self.assertFalse(self.w._loading)

    def test_tint_button_moves_the_glow_slider_without_resending(self):
        self.w._base_changed("404040")
        self.flush()
        self.assertEqual(self.sent, [{"base": "404040"}])
        self.w.glow_scale.set_value.assert_called_with(m.hex_to_glow("404040"))

    def test_save_profile_updates_list_and_clears_entry(self):
        self.w.profile_entry.get_text.return_value = "  Night "
        self.w._speed_changed(2.0)                              # pending edit must be sent first
        self.w._profile_save()
        self.assertEqual(self.sent[0], {"speed": 2.0})
        self.assertEqual(self.saved_profile[0], "Night")
        self.w.profile_model.splice.assert_called_with(0, 0, ["Night"])
        self.w.profile_entry.set_text.assert_called_with("")

    def test_save_profile_needs_a_name(self):
        self.w.profile_entry.get_text.return_value = "   "
        self.w._profile_save()
        self.assertEqual(self.profile_names, [])
        self.assertIn("name", self.w.status.set_text.call_args[0][0])

    def test_apply_profile_reloads_widgets(self):
        self.profile_names = ["Night"]
        self.w._set_profile_names(["Night"])
        self.w.profile_dropdown.get_selected.return_value = 0
        self.w.profile_model.get_n_items.return_value = 1
        self.w.profile_model.get_string.return_value = "Night"
        self.w._profile_apply()
        self.assertEqual(self.loaded, "Night")
        self.assertEqual(self.w.cfg["mode"], "static")
        self.w.mode_buttons["static"].set_active.assert_called_with(True)

    def test_apply_and_delete_do_nothing_without_selection(self):
        self.w.profile_dropdown.get_selected.return_value = 4294967295
        self.w._profile_apply()
        self.w._profile_delete()
        self.assertFalse(hasattr(self, "loaded"))

    def test_delete_profile(self):
        self.profile_names = ["Night", "Day"]
        self.w.profile_dropdown.get_selected.return_value = 0
        self.w.profile_model.get_n_items.return_value = 2
        self.w.profile_model.get_string.return_value = "Night"
        self.w._profile_delete()
        self.assertEqual(self.profile_names, ["Day"])

    def test_profile_error_goes_to_status_line(self):
        self.w.profile_entry.get_text.return_value = "../bad"
        with mock.patch.object(self.gui.client, "save_profile", side_effect=client.ClientError("bad name")):
            self.w._profile_save()
        self.assertIn("bad name", self.w.status.set_text.call_args[0][0])

    def test_punch_slider_sends_value(self):
        self.w._punch_changed(0.7)
        self.flush()
        self.assertEqual(self.sent, [{"punch": 0.7}])

    def test_edits_during_loading_are_ignored(self):
        self.w._loading = True
        self.w._speed_changed(2.0)
        self.w._zone_changed(0, "FFFFFF")
        self.w._loading = False
        self.flush()
        self.assertEqual(self.sent, [])

    def test_service_down_disables_controls(self):
        with mock.patch.object(self.gui.client, "get", side_effect=client.ClientError("not running")):
            self.w.refresh()
        self.w.controls.set_sensitive.assert_called_with(False)
        self.assertIn("not running", self.w.status.set_text.call_args[0][0])

    def test_external_change_is_picked_up_when_idle(self):
        self.cfg = config.merge(self.cfg, {"mode": "wave"})
        self.w._last_edit = 0.0
        self.w.refresh()
        self.assertEqual(self.w.cfg["mode"], "wave")

    def test_external_change_not_applied_while_editing(self):
        self.w._speed_changed(2.0)                           # pending edit
        self.cfg = config.merge(self.cfg, {"mode": "wave"})
        self.w.refresh()
        self.assertEqual(self.w.cfg["mode"], "ripple")


if __name__ == "__main__":
    unittest.main()
