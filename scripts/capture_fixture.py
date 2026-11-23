"""Saves the DART answers the tests replay, with the exact requests the contract makes.
    python -X utf8 scripts/capture_fixture.py
Bodies are kept byte for byte (base64): exchange filings are served in MS949."""
import base64, json, re, time, urllib.request
from pathlib import Path

DART = "https://dart.fss.or.kr"
OUT = Path(__file__).parent.parent / "tests" / "fixtures" / "dart.json"
SEARCH = ("/dsab007/detailSearch.ax?currentPage=1&maxResults=100&maxLinks=10&sort=date&series=desc"
          "&textCrpNm=&textCrpCik=%s&startDate=%s&endDate=%s&reportName=%s&reportNamePopYn=N")
RUMOR = "%ED%92%8D%EB%AC%B8"
# company, first day, last day of the rumor lists, and the filings the tests read
LISTS = [
    ("00190321", "20260626", "20261123", RUMOR),   # KT
    ("00781202", "20260929", "20261123", RUMOR), ("00781202", "20260929", "20261019", RUMOR),
    ("00781202", "20261019", "20261019", ""),      # every filing that day
    ("00164645", "20260709", "20261123", RUMOR), ("00164645", "20260709", "20261015", RUMOR),
    ("00164645", "20261015", "20261015", ""),      # HMM
    ("00153393", "20260504", "20261123", RUMOR),   # Taekwang
]
FILINGS = ["20260626800212", "20260724800564", "20261023800988", "20261117800141",
           "20260929900633", "20261019900583",
           "20260709800131", "20260807800131", "20261015800543",
           "20260504800294", "20260602800382", "20260610800321", "20260622800276", "20260901800368",
           "20260907800332", "20260911800691", "20261006800460",
           "20261112800376"]


def get(path):
    time.sleep(0.6)
    return urllib.request.urlopen(urllib.request.Request(DART + path, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()


out = {}
for corp, a, b, name in LISTS:
    path = SEARCH % (corp, a, b, name)
    out[path] = get(path)
for rcp in FILINGS:
    path = f"/dsaf001/main.do?rcpNo={rcp}"
    page = get(path).decode("utf-8")
    # the viewer page is 35 kB of scripts: keep the lines the contract reads
    keep = [l for l in page.split("\n") if "<title>" in l or "openCorpInfoNew('" in l or f'viewDoc("{rcp}"' in l]
    out[path] = "\n".join(keep).encode("utf-8")
    v = re.search(r'viewDoc\("%s", "(\d+)", "0", "0", "0", "HTML"' % rcp, page)
    if v:
        path = f"/report/viewer.do?rcpNo={rcp}&dcmNo={v.group(1)}&eleId=0&offset=0&length=0&dtd=HTML"
        out[path] = get(path)
OUT.write_text(json.dumps({k: base64.b64encode(v).decode() for k, v in out.items()}, indent=0), encoding="utf-8")
print(len(out), OUT.stat().st_size)
