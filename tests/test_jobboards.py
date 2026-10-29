from datetime import datetime, timezone

from jobscan import jobboards

LI_PAGE = """
<li>
  <div class="base-card relative w-full" data-entity-urn="urn:li:jobPosting:4476984167">
    <a class="base-card__full-link" href="https://www.linkedin.com/jobs/view/machine-learning-engineer-at-stripe-4476984167?trk=x"></a>
    <div class="base-search-card__info">
      <h3 class="base-search-card__title">
            Machine Learning Engineer, Radar
      </h3>
      <h4 class="base-search-card__subtitle">
          <a class="hidden-nested-link" href="https://www.linkedin.com/company/stripe">
            Stripe
          </a>
      </h4>
      <div class="base-search-card__metadata">
        <span class="job-search-card__location">
          Seattle, WA
        </span>
        <time class="job-search-card__listdate--new" datetime="2026-10-29">
          2 hours ago
        </time>
      </div>
    </div>
  </div>
</li>
<li><div>not a job card</div></li>
"""


def test_parse_linkedin():
    posts = jobboards.parse_linkedin(LI_PAGE)
    assert len(posts) == 1
    p = posts[0]
    assert (p.job_id, p.title, p.company, p.location) == ("4476984167", "Machine Learning Engineer, Radar", "Stripe", "Seattle, WA")
    assert p.url == "https://www.linkedin.com/jobs/view/4476984167"
    assert p.posted_at == datetime(2026, 10, 29, tzinfo=timezone.utc)


def test_map_builtin():
    p = jobboards.map_builtin([{"jobId": "11968189", "title": "Machine Learning Engineer", "jobUrl": "https://builtin.com/job/x/11968189",
                                "company": "Capital One", "location": "McLean, VA, USA", "postedDate": "2026-10-29",
                                "salaryText": "230K-286K Annually", "description": "<p>Build ML</p>"}])[0]
    assert p.uid == "builtin:builtin:11968189" and p.description == "Build ML" and p.extra["comp"].startswith("230K")


def test_map_hiringcafe():
    p = jobboards.map_hiringcafe([{"id": "utipro___boi___abc", "apply_url": "https://recruiting2.ultipro.com/x",
                                   "job_information": {"title": "Machine Learning Engineer", "descriptionText": "Azure ML"},
                                   "v5_processed_job_data": {"company_name": "Boise Cascade", "formatted_workplace_location": "United States",
                                                             "estimated_publish_date": "2026-10-29T19:15:53.278Z",
                                                             "yearly_min_compensation": 100000, "yearly_max_compensation": 150000}}])[0]
    assert p.company == "Boise Cascade" and p.extra["comp"] == "$100K-$150K" and p.posted_at.hour == 19


def test_map_jobright_drops_citizen_only_and_cleans_title():
    items = [{"id": "a", "title": "ML Engineer Job Details | Acme", "companyName": "Acme", "location": "Austin, TX",
              "url": "u", "postedAt": "2026-10-29T21:46:06Z", "isH1bSponsor": True, "description": "x"},
             {"id": "b", "title": "AI Engineer", "companyName": "Gov", "isCitizenOnly": True}]
    out = jobboards.map_jobright(items)
    assert [p.job_id for p in out] == ["a"] and out[0].title == "ML Engineer" and out[0].extra["h1b"]


def test_apify_runs_once_a_day():
    cfg = {"run_hours_utc": [15, 16]}
    assert jobboards.apify_due(cfg, datetime(2026, 11, 2, 15, 20, tzinfo=timezone.utc))
    assert not jobboards.apify_due(cfg, datetime(2026, 11, 2, 20, 10, tzinfo=timezone.utc))
