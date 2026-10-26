"""Unit tests for parsing, analysis, YouTube classification, records extraction, scoring, request drafts."""
from __future__ import annotations

import sys
import unittest
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from helpers import fixture  # noqa: E402

from bch import analysis, feeds, records, scoring, youtube  # noqa: E402
from bch.models import Agency, BodycamStatus, Verification, YouTubeStatus  # noqa: E402
from bch.request_writer import draft_request  # noqa: E402


class FeedTests(unittest.TestCase):
    def test_google_news_parse(self):
        items = feeds.parse_feed(fixture("google_news.xml"))
        self.assertEqual(len(items), 5)
        head, outlet = feeds.split_google_title(items[0].title, items[0].source_name)
        self.assertEqual(outlet, "Example News 8")
        self.assertTrue(head.startswith("Man leads Mockingbird County deputies"))
        self.assertEqual(items[0].published, datetime(2026, 10, 22, 14, 5))

    def test_bing_parse_and_link_resolution(self):
        items = feeds.parse_feed(fixture("bing_news.xml"))
        self.assertEqual(len(items), 2)
        self.assertEqual(items[0].source_name, "Example Tribune")
        self.assertEqual(feeds.resolve_bing_link(items[0].link), "https://news.example.com/2026/10/22/tractor-chase")
        self.assertIn("slow-speed chase", feeds.strip_html(items[0].summary))

    def test_etree_fallback(self):
        items = feeds._parse_with_etree(fixture("bing_news.xml"))
        self.assertEqual(items[1].source_name, "Example Ohio")

    def test_find_feed_links(self):
        html = '<html><head><link rel="alternate" type="application/rss+xml" href="/feed.xml"></head></html>'
        self.assertEqual(feeds.find_feed_links(html, "https://x.example.gov/news"), ["https://x.example.gov/feed.xml"])


class AnalysisTests(unittest.TestCase):
    TEXT = ("TESTVILLE, Fla. — A man stole a farm tractor and led Mockingbird County Sheriff’s Office "
            "deputies on a slow-speed chase Wednesday night before driving it into a pond. Deputies identified "
            "the driver as Grady Wayne Pruitt, 41, of Testville. The sheriff's office released body camera "
            "footage showing deputies pulling him out.")

    def test_relevance(self):
        self.assertTrue(analysis.is_relevant(self.TEXT)[0])
        self.assertFalse(analysis.is_relevant("City council approves new police budget")[0])
        self.assertFalse(analysis.is_relevant("Hurricane season forecast released")[0])

    def test_categories(self):
        cats = analysis.detect_categories(self.TEXT)
        self.assertEqual(set(cats[:2]), {"pursuit", "bizarre"})
        self.assertIn("bizarre", cats)  # "stole a farm tractor", "driving it into a pond"
        self.assertEqual(analysis.detect_categories("Driver arrested for OWI after crash")[0], "dui")

    def test_agency_and_location(self):
        name, basis = analysis.pick_agency([self.TEXT], "Florida")
        self.assertEqual(name, "Mockingbird County Sheriff's Office")
        self.assertEqual(basis, "named in source")
        city, county, lbasis = analysis.extract_location(self.TEXT, "Florida", name)
        self.assertEqual((city, county), ("Testville", "Mockingbird County"))
        self.assertEqual(lbasis, "article dateline")

    def test_agency_variants(self):
        names = [n for n, _ in analysis.extract_agencies(
            "Akron police say a driver fled on Oct. 18; Ohio State Highway Patrol assisted", "Ohio")]
        self.assertIn("Ohio State Highway Patrol", names)
        self.assertIn("Akron Police Department", names)
        self.assertNotIn("Oct. Ohio State Highway Patrol", names)
        self.assertEqual(analysis.extract_agencies("Milwaukee PD: suspect arrested", "Wisconsin")[0][0],
                         "Milwaukee Police Department")
        self.assertEqual(analysis.extract_agencies("Harris County deputies tased the man", "Texas")[0],
                         ("Harris County Sheriff's Office", "inferred from '<county> deputies' wording"))

    def test_incident_dates(self):
        pub = datetime(2026, 10, 22, 15, 0)  # Thursday
        d, basis, ev = analysis.extract_incident_date(self.TEXT, pub, "Florida")
        self.assertEqual(d, date(2026, 10, 21))
        self.assertEqual(basis, "derived from weekday in source")
        d, basis, _ = analysis.extract_incident_date("The crash happened on Oct. 18 near the mall", pub, "Ohio")
        self.assertEqual((d, basis), (date(2026, 10, 18), "date stated in source"))
        d, basis, _ = analysis.extract_incident_date("He is due in court on Nov. 3", pub, "Ohio")
        self.assertIsNone(d)  # court dates are not incident dates
        d, basis, _ = analysis.extract_incident_date("Police said nothing about when", pub, "Ohio")
        self.assertIsNone(d)
        self.assertEqual(basis, "not stated in checked sources")
        d, _, _ = analysis.extract_incident_date("Deputies responded Dec. 30", datetime(2026, 1, 2), "Ohio")
        self.assertEqual(d, date(2025, 12, 30))  # rolls back a year, never into the future

    def test_bodycam_and_suspects(self):
        st, ev = analysis.detect_bodycam(self.TEXT, ["pursuit"], "x")
        self.assertEqual(st, BodycamStatus.RELEASED)
        self.assertIn("body camera", ev)
        st, _ = analysis.detect_bodycam("Deputies arrested a man after a chase", ["pursuit"], "Some PD")
        self.assertEqual(st, BodycamStatus.LIKELY)
        st, _ = analysis.detect_bodycam("Deputies arrested a man", ["arrest"], None)
        self.assertEqual(st, BodycamStatus.UNKNOWN)
        self.assertEqual(analysis.extract_suspects(self.TEXT), ["Grady Wayne Pruitt"])

    def test_risk_flags(self):
        flags = {f["flag"] for f in analysis.risk_flags("A 15-year-old was shot and killed; the case remains under investigation")}
        self.assertTrue({"minor", "graphic", "ongoing", "monetization"} <= flags)
        self.assertEqual(analysis.risk_flags("Man arrested for stealing a tractor"), [])

    def test_states(self):
        self.assertEqual(analysis.resolve_state("Woman arrested in Kenosha, Wis., police say", None),
                         ("Wisconsin", "named in source"))
        self.assertEqual(analysis.resolve_state("Man arrested after chase", "Ohio"),
                         ("Ohio", "search region (not stated in source)"))

    def test_duplicate_clustering(self):
        pub = datetime(2026, 10, 22, 12)
        mk = lambda k, t, txt="": analysis.Candidate(  # noqa: E731
            key=k, title=t, text=txt, published=pub, state="Florida",
            agency="Mockingbird County Sheriff's Office", city="Testville",
            categories=analysis.detect_categories(t + txt))
        a = mk("a", "Man leads Mockingbird County deputies on chase in stolen tractor")
        b = mk("b", "Man stole farm tractor, led deputies on chase, Mockingbird County sheriff says")
        c = analysis.Candidate(key="c", title="Testville police: driver fled DUI stop, crashed into canal",
                               text="", published=pub, state="Florida", agency="Testville Police Department",
                               city="Testville", categories=["dui", "pursuit"])
        groups = analysis.cluster([a, b, c])
        self.assertEqual(sorted(len(g) for g in groups), [1, 2])


class YouTubeTests(unittest.TestCase):
    CTX = youtube.CaseContext(headline="Man leads Mockingbird County deputies on chase in stolen tractor",
                              state="Florida", city="Testville", county="Mockingbird County",
                              agency="Mockingbird County Sheriff's Office", incident_date=date(2026, 10, 21),
                              published=datetime(2026, 10, 22), categories=["pursuit"], suspects=["Grady Wayne Pruitt"])

    def _videos(self):
        import json
        out = []
        for it in json.loads(fixture("yt_videos.json"))["items"]:
            sn = it["snippet"]
            out.append({"video_id": it["id"], "title": sn["title"], "description": sn["description"],
                        "channel_title": sn["channelTitle"], "published_at": youtube._parse_dt(sn["publishedAt"]),
                        "view_count": int(it["statistics"]["viewCount"])})
        return out

    def test_classification(self):
        self.assertEqual(youtube.channel_kind("Example News 8"), "news")
        self.assertEqual(youtube.channel_kind("WXYZ-TV Detroit"), "news")
        self.assertEqual(youtube.channel_kind("Mockingbird County Sheriff's Office"), "agency")
        self.assertEqual(youtube.channel_kind("Code Blue Cam"), "commentary")
        self.assertEqual(youtube.footage_signal("Bodycam shows wild arrest", "")[0], True)
        self.assertEqual(youtube.footage_signal("Family demands police release bodycam", "")[0], True)
        self.assertEqual(youtube.footage_signal("Family calls for release of video", "")[0], False)

    def test_matching_and_status(self):
        assessed = youtube.assess_videos(self._videos(), self.CTX)
        by_id = {v["video_id"]: v for v in assessed}
        self.assertGreaterEqual(by_id["vidMATCH001"]["match_confidence"], youtube.MATCH_THRESHOLD)
        self.assertGreaterEqual(by_id["vidNEWS0003"]["match_confidence"], youtube.MATCH_THRESHOLD)
        self.assertLess(by_id["vidOTHER002"]["match_confidence"], youtube.MATCH_THRESHOLD)  # Texas, other incident
        self.assertEqual(youtube.coverage_status(assessed), YouTubeStatus.NEWS)
        self.assertEqual(youtube.coverage_status([]), YouTubeStatus.NONE_FOUND)
        only_other = [v for v in assessed if v["video_id"] == "vidOTHER002"]
        self.assertEqual(youtube.coverage_status(only_other), YouTubeStatus.RELATED_OTHER)

    def test_footage_status(self):
        vids = self._videos()
        vids[0]["title"] = "BODYCAM: Mockingbird County deputies pull tractor thief from pond in Testville"
        self.assertEqual(youtube.coverage_status(youtube.assess_videos(vids, self.CTX)), YouTubeStatus.FOOTAGE)

    def test_queries(self):
        qs = youtube.build_queries(self.CTX, 3)
        self.assertEqual(qs[0], '"Grady Wayne Pruitt" Testville')
        self.assertTrue(any("Mockingbird County deputies" in q for q in qs))
        self.assertEqual(youtube.iso_duration_to_text("PT1H2M3S"), "1:02:03")


class RecordsTests(unittest.TestCase):
    def test_extract_records_info(self):
        info = records.extract_records_info(fixture("agency_records.html"),
                                            "https://mockingbirdsheriff.gov/divisions/records")
        self.assertTrue(info["is_records_page"])
        self.assertEqual(info["portals"][0]["platform"], "NextRequest")
        self.assertIn("publicrecords@mockingbirdsheriff.gov", [e["email"] for e in info["emails"]])
        self.assertTrue(any("$32.50" in f for f in info["fees"]))
        self.assertEqual(info["phones"], ["(555) 555-0142"])

    def test_candidate_domains(self):
        ag = Agency(name="Mockingbird County Sheriff's Office", normalized_name="x", state="Florida",
                    county="Mockingbird County")
        doms = records.candidate_gov_domains(ag)
        self.assertEqual(doms[0], "mockingbirdsheriff.gov")
        self.assertTrue(all(d.endswith(".gov") or d.endswith(".us") for d in doms))

    def test_trust_helpers(self):
        ag = Agency(name="X", normalized_name="x", portal_url="https://a.example.com",
                    portal_status=Verification.UNVERIFIED, records_email="a@b.gov", email_status=Verification.OFFICIAL_SITE)
        self.assertIsNone(records.trusted_portal(ag))  # unverified links are never presented as the portal
        self.assertEqual(records.trusted_email(ag), "a@b.gov")


class ScoringTests(unittest.TestCase):
    def base(self, **kw):
        args = dict(headline="Man leads deputies on chase in stolen tractor", text="", categories=["pursuit"],
                    outlets=3, has_official_source=False, agency_basis="named in source",
                    bodycam_status=BodycamStatus.MENTIONED, youtube_status=YouTubeStatus.NONE_FOUND,
                    matched_videos=[], incident_date=date(2026, 10, 21), first_published=None, state="Florida",
                    risk=[], trusted_portal=True, records_page=True, suspects=["A B"], today=date(2026, 10, 24))
        args.update(kw)
        return scoring.score_case(**args)

    def test_unpublished_beats_published(self):
        good, bd = self.base()
        bad, _ = self.base(youtube_status=YouTubeStatus.FOOTAGE, matched_videos=[{"view_count": 900_000}])
        self.assertGreater(good, bad + 20)
        self.assertEqual(set(bd["components"]), {"interest", "audience", "footage_likelihood", "unpublished",
                                                 "competition", "recency", "acquisition", "reliability"})
        self.assertLessEqual(sum(c["max"] for c in bd["components"].values()), 100)

    def test_pa_window_and_penalties(self):
        _, bd = self.base(state="Pennsylvania", incident_date=date(2026, 7, 1))
        self.assertEqual(bd["components"]["acquisition"]["points"], 0)
        s1, _ = self.base()
        s2, bd2 = self.base(risk=[{"flag": "minor", "label": "Minor"}])
        self.assertEqual(s1 - s2, 4)
        self.assertEqual(bd2["penalties"][0]["points"], -4)

    def test_ai_is_labeled(self):
        _, bd = self.base(ai={"interest_score": 9, "interest_reason": "odd", "footage_likelihood": 5})
        self.assertEqual(bd["components"]["interest"]["basis"], "rule + AI estimate")

    def test_cost_estimate(self):
        self.assertEqual(scoring.estimate_cost("Ohio", None)[0], 75.0)
        self.assertEqual(scoring.estimate_cost("Florida", None), (None, None))
        self.assertEqual(scoring.estimate_cost("Florida", "Body worn camera video $32.50 per hour")[0], 32.5)


class RequestWriterTests(unittest.TestCase):
    CASE = {"headline": "Tractor chase", "state": "Texas", "city": "Testville", "county": "Mock County",
            "incident_date": date(2026, 10, 21), "suspect_names": ["Grady Wayne Pruitt"],
            "sources": ["https://news.example.com/a"]}

    def test_texas_elements(self):
        t = draft_request(case=self.CASE, agency_name="Testville Police Department",
                          contact={"name": "Jordan", "email": "j@example.com"}, budget=100, approx_time="10 PM",
                          today=date(2026, 10, 24))
        self.assertIn("1701.661", t)
        self.assertIn("Grady Wayne Pruitt", t)
        self.assertIn("October 21, 2026", t)
        self.assertIn("$100.00", t)
        self.assertNotIn("[FILL IN: your name]", t)

    def test_pa_and_placeholders(self):
        case = dict(self.CASE, state="Pennsylvania", incident_date=None)
        t = draft_request(case=case, agency_name=None, contact={}, budget=None)
        self.assertIn("Act 22", t)
        self.assertIn("certified mail", t)
        self.assertIn("[FILL IN: incident date]", t)
        self.assertIn("[FILL IN: agency name]", t)


if __name__ == "__main__":
    unittest.main()
