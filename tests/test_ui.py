"""Headless UI smoke tests using Streamlit's AppTest. Each page renders against a populated database."""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from streamlit.testing.v1 import AppTest
    HAVE_ST = True
except ImportError:  # pragma: no cover
    HAVE_ST = False

from helpers import install_fake_network, no_sleep_throttle, temp_db  # noqa: E402

PAGE_SCRIPT = """
import sys
sys.path.insert(0, {root!r})
import streamlit as st
{shim}
from bch.ui import common, {mod}
common.inject_css()
{mod}.render()
"""

# st.dataframe/st.data_editor need pyarrow. When it's missing (some CI sandboxes), swap in stand-ins that still
# validate the call and return the same shape of object, so the rest of each page is exercised.
PYARROW_SHIM = """
try:
    import pyarrow  # noqa: F401
except ImportError:
    from types import SimpleNamespace
    def _df(data=None, *a, **k):
        st.caption("[dataframe %s rows]" % (len(data) if hasattr(data, "__len__") else "?"))
        return SimpleNamespace(selection=SimpleNamespace(rows=[], columns=[]))
    def _ed(data=None, *a, **k):
        st.caption("[data_editor]")
        return data
    st.dataframe = _df
    st.data_editor = _ed
    st.bar_chart = lambda *a, **k: st.caption("[chart]")
"""


@unittest.skipUnless(HAVE_ST, "streamlit not installed")
class UITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp_db()
        from bch import db
        db.set_setting("states", ["Florida"])
        db.set_setting("categories", ["pursuit"])
        db.set_setting("request_contact", {"name": "Test User", "email": "test@example.com"})
        os.environ["YOUTUBE_API_KEY"] = "test-key"
        install_fake_network()
        no_sleep_throttle()
        from datetime import datetime
        from bch import pipeline
        frozen = datetime(2026, 10, 24, 18, 0)
        with mock.patch.multiple("bch.clock", utcnow=lambda: frozen, today=lambda: frozen.date()):
            res = pipeline.run_research(trigger="ui-test")
        assert res["status"] == "completed", res
        from sqlalchemy import select
        from bch.db import session_scope
        from bch.models import Case
        with session_scope() as s:
            cls.case_id = s.scalars(select(Case).where(Case.headline.ilike("%tractor%"))).first().id

    def page(self, mod: str, **state) -> "AppTest":
        at = AppTest.from_string(PAGE_SCRIPT.format(root=str(ROOT), mod=mod, shim=PYARROW_SHIM), default_timeout=60)
        for k, v in state.items():
            at.session_state[k] = v
        at.run()
        self.assertEqual(len(at.exception), 0, [e.message + "\n" + "\n".join(e.stack_trace) for e in at.exception])
        return at

    def test_overview(self):
        at = self.page("overview")
        labels = [m.label for m in at.metric]
        self.assertIn("Total cases", labels)
        self.assertIn("Pending requests", labels)
        self.assertGreaterEqual(int(next(m.value for m in at.metric if m.label == "Total cases")), 2)

    def test_discover(self):
        at = self.page("discover")
        self.assertTrue(any("cases match" in c.value for c in at.caption))
        at.text_input(key="f_search").input("tractor").run()
        self.assertEqual(len(at.exception), 0)
        self.assertTrue(any(c.value.startswith("1 of") for c in at.caption), [c.value for c in at.caption])

    def test_case_research(self):
        at = self.page("case_research", case_id=self.case_id)
        md = "\n".join(m.value for m in at.markdown)
        self.assertIn("Mockingbird County Sheriff's Office", md)
        self.assertIn("Criminal case research", md)
        self.assertIn("YouTube research", md)
        self.assertIn("Footage acquisition", md)
        # the verified portal appears as a link button
        link_labels = [e.proto.label for e in at.get("link_button")]
        self.assertIn("Open Records Request Portal", link_labels)

    def test_footage_generate_request(self):
        at = self.page("footage", case_id=self.case_id)
        at.button[[b.label for b in at.button].index("Generate request")].click().run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        codes = [c.value for c in at.code]
        letter = next((c for c in codes if "Records Custodian" in c), "")
        self.assertIn("Mockingbird County Sheriff's Office", letter)
        self.assertIn("Florida Public Records Act", letter)
        self.assertIn("Test User", letter)
        # save to tracker
        at.button[[b.label for b in at.button].index("Save to tracker as 'Ready to Request'")].click().run()
        self.assertEqual(len(at.exception), 0)
        from bch import services
        self.assertIn("Ready to Request", services.requests_frame()["Status"].tolist())

    def test_tracker(self):
        at = self.page("tracker")
        self.assertTrue(any(m.label == "Requests" for m in at.metric) or "No requests yet" in str(at))
        labels = [b.label for b in at.button]
        if "Save changes" in labels:
            at.button[labels.index("Save changes")].click().run()
            self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])

    def test_zz_case_status_update(self):
        at = self.page("case_research", case_id=self.case_id)
        at.selectbox(key="case_req_status").select("Submitted").run()
        labels = [b.label for b in at.button]
        at.button[labels.index("Update status")].click().run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        from bch import services
        df = services.requests_frame()
        self.assertIn("Submitted", df["Status"].tolist())
        self.assertTrue(df.loc[df["Status"] == "Submitted", "Submitted"].notna().all())

    def test_competition(self):
        at = self.page("competition")
        at.button[[b.label for b in at.button].index("Refresh uploads")].click().run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        md = "\n".join(m.value for m in at.markdown)
        self.assertIn("Example Bodycam Channel", md)
        self.assertIn("Subscribers", [m.label for m in at.metric])

    def test_footage_verify_and_edit(self):
        from bch.db import session_scope
        from bch.models import Agency, Case, Verification
        with session_scope() as s:
            ag = s.get(Case, self.case_id).agency
            ag.portal_status = Verification.UNVERIFIED
            aid = ag.id
        at = self.page("footage", case_id=self.case_id)
        self.assertIn("No verified request portal yet", [e.value for e in at.error])
        at.button(key=f"ver_portal_{aid}").click().run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        with session_scope() as s:
            self.assertEqual(s.get(Agency, aid).portal_status, Verification.USER_VERIFIED)
        self.assertNotIn("No verified request portal yet", [e.value for e in at.error])

    def test_agencies_add_feed_and_agency(self):
        at = self.page("agencies")
        at.text_input[[t.label for t in at.text_input].index("Feed URL (RSS/Atom)")].input("https://feeds.example.gov/news.rss")
        at.text_input[[t.label for t in at.text_input].index("Name")].input("Example Sheriff Newsroom")
        at.button[[b.label for b in at.button].index("Test & add feed")].click().run()
        self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
        self.assertTrue(any("Added" in s.value for s in at.success), [s.value for s in at.success] + [e.value for e in at.error])
        at.text_input[[t.label for t in at.text_input].index("Agency name")].input("Sample City Police Department")
        at.button[[b.label for b in at.button].index("Add agency")].click().run()
        self.assertEqual(len(at.exception), 0)
        from bch import services
        self.assertIn("Sample City Police Department", services.agencies_frame()["Agency"].tolist())

    def test_agencies(self):
        at = self.page("agencies")
        self.assertIn("Agencies", [t.label for t in at.tabs])

    def test_settings(self):
        import tempfile
        from bch import config
        env = Path(tempfile.mkdtemp()) / ".env"
        with mock.patch.object(config, "ENV_PATH", env):
            at = self.page("settings_page")
            self.assertEqual(len(at.tabs), 5)
            at.button[[b.label for b in at.button].index("Save research settings")].click().run()
            self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
            at.text_input[[t.label for t in at.text_input].index("Name")].input("Jordan Test")
            at.button[[b.label for b in at.button].index("Save details")].click().run()
            self.assertEqual(len(at.exception), 0)
            from bch.db import get_setting
            self.assertEqual(get_setting("request_contact")["name"], "Jordan Test")
            at.button[[b.label for b in at.button].index("Save keys")].click().run()
            self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])
            at.button[[b.label for b in at.button].index("Test YouTube key")].click().run()
            self.assertEqual(len(at.exception), 0, [e.message for e in at.exception])

    def test_full_app_navigation(self):
        at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60)
        # Run through the real entry point (navigation + sidebar). pyarrow shim applied via sys.modules patch.
        try:
            import pyarrow  # noqa: F401
        except ImportError:
            import streamlit as st
            from types import SimpleNamespace
            with mock.patch.object(st, "dataframe", lambda *a, **k: SimpleNamespace(selection=SimpleNamespace(rows=[]))):
                at.run()
        else:
            at.run()
        self.assertEqual(len(at.exception), 0, [e.message + "\n".join(e.stack_trace) for e in at.exception])
        self.assertEqual(at.title[0].value, "Bodycam Research Hub")


if __name__ == "__main__":
    unittest.main()
