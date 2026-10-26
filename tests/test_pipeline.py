"""End-to-end pipeline test with a fake network (no internet needed)."""
from __future__ import annotations

import os
import sys
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import install_fake_network, no_sleep_throttle, temp_db  # noqa: E402

FROZEN_NOW = datetime(2026, 10, 24, 18, 0)



def frozen():
    """Freeze the app clock so the fixture dates (Oct 2026) always look recent."""
    return mock.patch.multiple("bch.clock", utcnow=lambda: FROZEN_NOW, today=lambda: FROZEN_NOW.date())


class PipelineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = temp_db()
        from bch import db
        db.set_setting("states", ["Florida"])
        db.set_setting("categories", ["pursuit", "dui"])
        db.set_setting("youtube_max_cases_per_run", 5)
        db.set_setting("request_contact", {"name": "Test User", "email": "test@example.com"})
        os.environ["YOUTUBE_API_KEY"] = "test-key"
        os.environ.pop("AI_PROVIDER", None)
        cls.fake = install_fake_network()
        no_sleep_throttle()
        from bch import pipeline
        with frozen():
            cls.result = pipeline.run_research(trigger="test")

    def test_run_completed(self):
        self.assertEqual(self.result["status"], "completed", "\n".join(self.result["log"]))

    def test_cases_deduplicated(self):
        from sqlalchemy import select
        from bch.db import session_scope
        from bch.models import Case
        with session_scope() as s:
            cases = s.scalars(select(Case)).all()
            heads = [c.headline for c in cases]
            tractor = [c for c in cases if "tractor" in c.headline.lower()]
            # 2 Google + 1 Bing tractor stories collapse into one case
            self.assertEqual(len(tractor), 1, heads)
            self.assertGreaterEqual(len(tractor[0].articles), 3)
            # policy story and the June story are filtered out
            self.assertFalse(any("budget" in h.lower() for h in heads))
            self.assertFalse(any("2019" in h for h in heads))

    def test_tractor_case_fields(self):
        from sqlalchemy import select
        from bch.db import session_scope
        from bch.models import BodycamStatus, Case, Verification, YouTubeStatus
        with session_scope() as s:
            c = s.scalars(select(Case).where(Case.headline.ilike("%tractor%"))).first()
            self.assertEqual(c.state, "Florida")
            self.assertEqual(c.agency_name, "Mockingbird County Sheriff's Office")
            self.assertEqual(str(c.incident_date), "2026-10-21")
            self.assertEqual(c.incident_date_basis, "derived from weekday in source")
            self.assertEqual(c.bodycam_status, BodycamStatus.RELEASED)  # article says footage was released
            self.assertIn("Grady Wayne Pruitt", c.suspect_names)
            self.assertEqual(c.youtube_status, YouTubeStatus.NEWS)
            self.assertTrue(any(v.match_confidence >= 55 for v in c.videos))
            ag = c.agency
            self.assertEqual(ag.website, "https://mockingbirdsheriff.gov/")
            self.assertEqual(ag.website_status, Verification.OFFICIAL_SITE)
            self.assertEqual(ag.portal_url, "https://mockingbirdso.nextrequest.com/")
            self.assertEqual(ag.portal_status, Verification.OFFICIAL_SITE)
            self.assertEqual(ag.records_email, "publicrecords@mockingbirdsheriff.gov")
            self.assertIn("$32.50", ag.fee_info)
            self.assertGreater(c.score, 0)
            self.assertIn("components", c.score_breakdown)
            self.assertEqual(c.est_cost, 32.5)

    def test_out_of_area_hidden(self):
        from sqlalchemy import select
        from bch.db import session_scope
        from bch.models import Case
        with session_scope() as s:
            ohio = s.scalars(select(Case).where(Case.headline.ilike("%kayaker%"))).first()
            self.assertIsNotNone(ohio)
            self.assertEqual(ohio.state, "Ohio")
            self.assertTrue(ohio.hidden)

    def test_second_run_is_idempotent(self):
        from sqlalchemy import func, select
        from bch import pipeline
        from bch.db import session_scope
        from bch.models import Article, Case
        with session_scope() as s:
            n_cases = s.scalar(select(func.count(Case.id)))
            n_arts = s.scalar(select(func.count(Article.id)))
        with frozen():
            res = pipeline.run_research(trigger="test2")
        self.assertEqual(res["status"], "completed")
        with session_scope() as s:
            self.assertEqual(s.scalar(select(func.count(Case.id))), n_cases)
            self.assertEqual(s.scalar(select(func.count(Article.id))), n_arts)

    def test_quota_tracked_and_cached(self):
        from bch import youtube
        with frozen():
            used = youtube.quota_used_today()
        self.assertGreater(used, 0)
        self.assertLessEqual(used, 5 * 101 + 10)

    def test_no_unrouted_requests_to_real_sites(self):
        for url in self.fake.calls:
            self.assertTrue(any(h in url for h in (
                "news.google.com", "bing.com", "example.", "mockingbird", "googleapis.com",
                "testville", "mockingbirdcounty", "cityof", "co.", "ci.")), url)


if __name__ == "__main__":
    unittest.main()
