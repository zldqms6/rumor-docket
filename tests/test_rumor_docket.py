import base64
import json
import re
from datetime import datetime, timezone
from pathlib import Path

CONTRACT = "contracts/rumor_docket.py"
DART = "https://dart.fss.or.kr"
GEN = 10**18
FEE = GEN // 10
# Filing bodies are DART's own pages, byte for byte (exchange filings are MS949). Frames
# are cut to the lines the contract reads. The search pages hold the real rows, put back
# into DART's row markup by hand: DART cut my address off before they were saved whole.
# scripts/capture_fixture.py replaces all of it with fresh captures.
FX = {k: base64.b64decode(v) for k, v in
      json.loads((Path(__file__).parent / "fixtures" / "dart.json").read_text(encoding="utf-8")).items()}
LAST = "20261123"                # the day the lists were captured

KT = "20260626800212"            # KT: "KT Cloud merger"
KT_2, KT_3, KT_FUNDING = "20260724800564", "20261023800988", "20261117800141"
PION = "20260929900633"          # creditor's bankruptcy petition rumor
PION_PETITION = "20261019900583"
HMM, HMM_2, HMM_SHIPS = "20260709800131", "20260807800131", "20261015800543"
TK = "20260504800294"            # Taekwang: Nexflex
TK_ALL = ["20260602800382", "20260610800321", "20260622800276", "20260901800368", "20260907800332", "20260911800691"]
TK_NEXFLEX = {"20260602800382", "20260901800368", "20260911800691"}
DAEWOONG_FIX = "20261112800376"  # a correction


def day(s):
    """Noon in Seoul."""
    return datetime(int(s[:4]), int(s[4:6]), int(s[6:8]), 3, tzinfo=timezone.utc).isoformat()


def body_text(rcp):
    raw = next(v for k, v in FX.items() if k.startswith(f"/report/viewer.do?rcpNo={rcp}"))
    t = re.sub(r"(?is)<style.*?</style>", "", raw.decode("cp949"))
    return re.sub(r"\s+", " ", re.sub(r"<[^>]*>", " ", t))


def sentence(rcp):
    """Some real sentence of the filing, to quote."""
    return re.search(r"(당사[^.]{15,120}|본 공시는[^.]{15,80})", body_text(rcp)).group(1).strip()


def answer(rcp, same, outcome="UNDECIDED"):
    return json.dumps({"same_rumor": same, "outcome": outcome, "quote": sentence(rcp) if same else ""}, ensure_ascii=False)


def search_path(corp, a, b, rumor=True):
    return ("/dsab007/detailSearch.ax?currentPage=1&maxResults=100&maxLinks=10&sort=date&series=desc&textCrpNm="
            f"&textCrpCik={corp}&startDate={a}&endDate={b}&reportName={'%ED%92%8D%EB%AC%B8' if rumor else ''}&reportNamePopYn=N")


def serve(vm, *llm, override=None, today=None):
    """Every captured page at its exact URL, plus the LLM answers."""
    vm.clear_mocks()
    if today:
        vm.warp(day(today))
    pages = dict(FX)
    pages.update(override or {})
    for path, raw in pages.items():
        status, body = raw if isinstance(raw, tuple) else (200, raw)
        vm.mock_web("^" + re.escape(DART + path) + "$", {"method": "GET", "status": status, "body": body})
    for pattern, reply in llm:
        vm.mock_llm(pattern, reply)


def for_filing(rcp, reply):
    """Answer only when the prompt's new filing is this one: no two filings used here share a day."""
    return (rf'(?s)<new_filing form="[^"]*" received="{rcp[:4]}-{rcp[4:6]}-{rcp[6:8]}">', reply)


def rows_until(corp, a, last):
    """The captured list as it looked on an earlier day: rows filed after it removed."""
    page = FX[search_path(corp, a, LAST)].decode("utf-8")
    kept = []

    def keep(m):
        r = re.search(r"rcpNo=(\d{14})", m.group(0))
        if r and r.group(1)[:8] > last:
            return ""
        if r:
            kept.append(r.group(1))
        return m.group(0)

    page = re.sub(r"<tr>.*?</tr>", keep, page, flags=re.S)
    page = re.sub(r"\[총\s*[\d,]+건\]", f"[총 {len(kept)}건]" if kept else "조회 결과가 없습니다", page)
    return {search_path(corp, a, last): page.encode("utf-8")}


def gl_error(msg):
    return Exception({"does not fit on one page": "[EXTERNAL] DART's list does not fit on one page",
                      "another company": "[TRANSIENT] DART listed a filing of another company",
                      "no total": "[TRANSIENT] DART's list has no total",
                      "HTTP 503": "[TRANSIENT] DART returned HTTP 503"}[msg])


def opened(vm, c, rcp, sender, pot=GEN, fee=FEE, today=LAST):
    serve(vm, today=today)
    vm.sender, vm.value = sender, pot
    r = c.open(rcp, fee)
    vm.value = 0
    return r["id"]


def step(vm, c, did, rcp, same, outcome="UNDECIDED", sender=None):
    serve(vm, for_filing(rcp, answer(rcp, same, outcome)), today=LAST)
    if sender is not None:
        vm.sender = sender
    r = c.advance(did)
    assert r["read"] == rcp
    return r


# ---------- reading ----------

def test_open_reads_company_headline_and_promised_date(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    expected = {
        TK: ("태광산업", "태광그룹, MBK 보유 넥스플렉스 인수 검토", "2026-06-02"),
        HMM: ("HMM", "벌크船도 초장기 계약...HMM 체질개선 속도", "2026-08-07"),
        PION: ("파이온엑스", "채권자에 의한 파산신청설에 대한 조회공시 답변", "2026-10-29"),   # KOSDAQ layout
        # a correction prints the whole filing again under a correction table
        DAEWOONG_FIX: ("대웅제약", "대웅제약, 신약 개발 계열사 아이엔테라퓨틱스 경영권 매각 추진", "2026-12-11"),
    }
    for rcp, want in expected.items():
        did = opened(direct_vm, c, rcp, direct_alice)
        d = c.get_docket(did)
        assert (d["company"], d["headline"], d["due"]) == want
        assert d["state"] == "undecided" and d["opened_rcp"] == rcp and c.find(rcp) == did
        assert direct_vm.run_validator() is True
    assert c.dockets_of("00164645") == [1] and c.dockets_of("00000000") == []
    assert c.find("20260101000000") == -1 and c.get_count() == 4


def test_open_refuses_what_does_not_start_a_rumor(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    direct_vm.sender = direct_alice
    serve(direct_vm, today=LAST)
    with direct_vm.expect_revert("open the docket on the first one"):     # names its earlier undecided reply
        c.open(HMM_2, 0)
    with direct_vm.expect_revert("open the docket on the first one"):
        c.open(KT_3, 0)
    with direct_vm.expect_revert("opens on an undecided rumor reply"):    # an untagged reply
        c.open("20260911800691", 0)
    with direct_vm.expect_revert("opens on an undecided rumor reply"):    # an investment decision
        c.open(HMM_SHIPS, 0)
    frame = FX[f"/dsaf001/main.do?rcpNo={KT}"].replace(b'"HTML"', b'"dart4.xsd"')
    serve(direct_vm, override={f"/dsaf001/main.do?rcpNo={KT}": frame})
    with direct_vm.expect_revert("not an exchange filing"):               # a report on DART's own form
        c.open(KT, 0)
    serve(direct_vm)
    for bad in ("2026062680021", "20261399800212", "abc", "19990101800212"):
        with direct_vm.expect_revert("14 digits"):
            c.open(bad, 0)
    c.open(KT, 0)
    with direct_vm.expect_revert("already has a docket"):
        c.open(KT, 0)


# ---------- following a thread ----------

def test_kt_rolled_twice_and_the_funding_rumor_is_another_one(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    assert step(direct_vm, c, did, KT_2, True, sender=direct_bob)["due"] == "2026-10-23"
    assert direct_vm.run_validator() is True
    r = step(direct_vm, c, did, KT_3, True)
    assert r["due"] == "2027-04-22" and r["left"] == 1
    assert c.status(did)["checked_at"] == 0                # one reply still unread
    step(direct_vm, c, did, KT_FUNDING, False)
    s = c.status(did)
    assert (s["state"], s["rolls"], s["days_late"], s["latest_rcp"]) == ("undecided", 2, 0, KT_3)
    assert s["due"] == "2027-04-22"                         # the other rumor's date is not taken over
    assert s["checked_at"] > 0
    d = c.get_docket(did)
    assert [f["same"] for f in d["filings"]] == [True, True, True, False]
    assert d["filings"][3]["due"] == ""                     # nor shown as this rumor's promise
    assert d["pot"] == GEN - 3 * FEE                        # every filing read pays, related or not
    serve(direct_vm, today=LAST)
    assert c.advance(did)["read"] == "" and c.get_docket(did)["pot"] == GEN - 3 * FEE


def test_taekwang_interleaved_rumors_end_in_a_denial(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, TK, direct_alice)
    for rcp in TK_ALL:
        r = step(direct_vm, c, did, rcp, rcp in TK_NEXFLEX, "DENIED" if rcp == TK_ALL[-1] else "UNDECIDED")
    assert r["state"] == "denied" and r["left"] > 0         # later filings exist, this rumor is over
    s = c.status(did)
    assert s["rolls"] == 2 and s["latest_rcp"] == TK_ALL[-1] and s["days_late"] == 0
    with direct_vm.expect_revert("docket is denied"):
        c.advance(did)


def test_the_caller_cannot_skip_a_reply(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, TK, direct_alice)
    # a later filing would end it, but the oldest unread one is always taken
    serve(direct_vm, for_filing(TK_ALL[-1], answer(TK_ALL[-1], True, "DENIED")),
          for_filing(TK_ALL[0], answer(TK_ALL[0], True)), today=LAST)
    assert c.advance(did)["read"] == TK_ALL[0]
    assert c.status(did)["state"] == "undecided"


def test_a_tag_on_the_form_beats_the_model(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    r = step(direct_vm, c, did, KT_2, True, "CONFIRMED")    # model says confirmed, the form says 미확정
    assert r["outcome"] == "UNDECIDED" and r["state"] == "undecided"


def test_a_correction_is_not_a_roll(direct_vm, direct_deploy, direct_alice):
    """KT's July reply, listed as if it were a correction of the June one."""
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    path = search_path("00190321", "20260626", LAST)
    page = FX[path].decode("utf-8")
    row = next(t for t in re.findall(r"<tr>.*?</tr>", page, re.S) if f"rcpNo={KT_2}" in t)
    fixed = re.sub(r"(?<=>)(\s*)조회공시요구", r"\1[기재정정]조회공시요구", row)
    assert fixed != row
    serve(direct_vm, for_filing(KT_2, answer(KT_2, True)), override={path: page.replace(row, fixed).encode("utf-8")}, today=LAST)
    c.advance(did)
    d = c.get_docket(did)
    assert d["rolls"] == 0 and d["filings"][1]["kind"] == "correction" and d["state"] == "undecided"
    assert d["due"] == "2026-10-23" and d["latest_rcp"] == KT_2
    serve(direct_vm, for_filing(KT_2, answer(KT_2, True)))
    assert direct_vm.run_validator() is False                # a validator whose list shows no correction


# ---------- promised dates ----------

def test_silent_after_the_promised_date(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, HMM, direct_alice)
    serve(direct_vm, today=LAST)
    with direct_vm.expect_revert("1 rumor replies have not been read"):     # the 08-07 answer did come
        c.mark_silent(did)
    step(direct_vm, c, did, HMM_2, True)
    assert c.status(did)["due"] == "2026-11-06"
    serve(direct_vm, today="20261109")                                       # exactly 3 days later: not yet
    with direct_vm.expect_revert("has not passed"):
        c.mark_silent(did)
    serve(direct_vm, today=LAST)
    direct_vm.sender = direct_bob
    r = c.mark_silent(did)
    assert r["state"] == "silent" and r["paid"] == FEE
    assert direct_vm.run_validator() is True
    s = c.status(did)
    assert s["silent_count"] == 1 and s["checked_at"] > 0
    # a validator whose list shows one more reply does not agree
    path = search_path("00164645", "20260709", LAST)
    page = FX[path].decode("utf-8")
    row = next(t for t in re.findall(r"<tr>.*?</tr>", page, re.S) if HMM_2 in t)
    page = page.replace(row, row.replace(HMM_2, "20261120800999") + row)
    page = re.sub(r"\[총\s*(\d+)건\]", lambda m: "[총 %d건]" % (int(m.group(1)) + 1), page)
    serve(direct_vm, override={path: page.encode("utf-8")})
    assert direct_vm.run_validator() is False
    serve(direct_vm)
    with direct_vm.expect_revert("docket is silent"):                        # once per promised date
        c.mark_silent(did)


def test_late_answer_is_counted_in_days(direct_vm, direct_deploy, direct_alice):
    """KT promised 2026-07-24; serve its July reply as if it had come on 07-29."""
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    late = "20260729800564"
    path = search_path("00190321", "20260626", LAST)
    old = next(k for k in FX if k.startswith(f"/report/viewer.do?rcpNo={KT_2}"))
    frame = f"/dsaf001/main.do?rcpNo={KT_2}"
    ov = {path: FX[path].replace(KT_2.encode(), late.encode()),
          frame.replace(KT_2, late): FX[frame].replace(KT_2.encode(), late.encode()),
          old.replace(KT_2, late): FX[old]}
    serve(direct_vm, for_filing(late, answer(KT_2, True)), override=ov, today=LAST)
    c.advance(did)
    assert c.status(did)["days_late"] == 5 and c.get_docket(did)["filings"][1]["late"] == 5


# ---------- the answer under another form ----------

def test_bankruptcy_petition_notice_settles_the_rumor(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, PION, direct_alice)
    assert "갈음" in body_text(PION_PETITION)               # the filing itself says it replaces the answer
    serve(direct_vm, for_filing(PION_PETITION, answer(PION_PETITION, True, "CONFIRMED")), today=LAST)
    direct_vm.sender = direct_bob
    r = c.close_with(did, PION_PETITION)
    assert r["settles"] and r["state"] == "confirmed" and r["paid"] == FEE
    assert direct_vm.run_validator() is True
    assert c.status(did)["days_late"] == 0                  # 10-19, promised 10-29
    for mine in (answer(PION_PETITION, False), answer(PION_PETITION, True, "DENIED")):
        serve(direct_vm, for_filing(PION_PETITION, mine))
        assert direct_vm.run_validator() is False


def test_settling_filing_before_the_date_undoes_silent(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, PION, direct_alice)
    serve(direct_vm, today=LAST)
    assert c.mark_silent(did)["state"] == "silent"          # no rumor form came after 09-29
    serve(direct_vm, for_filing(PION_PETITION, answer(PION_PETITION, True, "CONFIRMED")), today=LAST)
    c.close_with(did, PION_PETITION)
    s = c.status(did)
    assert (s["state"], s["silent_count"]) == ("confirmed", 0)


def test_refused_event_pays_nothing_and_cannot_be_retried(direct_vm, direct_deploy, direct_alice):
    """HMM's rumor is a long-term bulk carrier contract; the nominated filing buys container ships."""
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, HMM, direct_alice)
    no = for_filing(HMM_SHIPS, answer(HMM_SHIPS, False))
    serve(direct_vm, no, today=LAST)
    with direct_vm.expect_revert("advance first"):           # the 08-07 reply was never read
        c.close_with(did, HMM_SHIPS)
    step(direct_vm, c, did, HMM_2, True)
    serve(direct_vm, no, today=LAST)
    r = c.close_with(did, HMM_SHIPS)
    assert not r["settles"] and r["paid"] == 0 and r["state"] == "undecided"
    assert direct_vm.run_validator() is True
    serve(direct_vm, for_filing(HMM_SHIPS, answer(HMM_SHIPS, True, "CONFIRMED")), today=LAST)
    assert direct_vm.run_validator() is False
    with direct_vm.expect_revert("already looked at"):
        c.close_with(did, HMM_SHIPS)


def test_close_with_refuses_other_kinds_of_filings(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, PION, direct_alice)
    serve(direct_vm, today=LAST)
    with direct_vm.expect_revert("older than"):
        c.close_with(did, "20260928900777")
    with direct_vm.expect_revert("not made by the company itself"):     # the exchange's halt notice
        c.close_with(did, "20261019900622")
    with direct_vm.expect_revert("corrections are not events"):
        c.close_with(did, "20261019000322")
    with direct_vm.expect_revert("no such filing"):
        c.close_with(did, "20261019800001")
    serve(direct_vm, for_filing(PION_PETITION, answer(PION_PETITION, True, "UNDECIDED")), today=LAST)
    with direct_vm.expect_revert("[LLM_ERROR] invalid outcome"):         # an event must settle it
        c.close_with(did, PION_PETITION)


# ---------- consensus ----------

def test_validator_votes_on_its_own_reading(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, TK, direct_alice)
    for rcp in TK_ALL[:-1]:
        step(direct_vm, c, did, rcp, rcp in TK_NEXFLEX)
    last = TK_ALL[-1]
    step(direct_vm, c, did, last, True, "DENIED")
    assert direct_vm.run_validator() is True
    # same filings, but this validator's model reads a different outcome, or another rumor
    for mine in (answer(last, True, "CONFIRMED"), answer(last, True, "UNDECIDED"), answer(last, False),
                 "I think it is denied"):
        serve(direct_vm, for_filing(last, mine))
        assert direct_vm.run_validator() is False
    serve(direct_vm, for_filing(last, answer(last, True, "DENIED")))
    assert direct_vm.run_validator() is True


def test_lying_leader_is_refused(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    serve(direct_vm, for_filing(KT_2, answer(KT_2, True)), today=LAST)
    c.advance(did)
    f = c.get_docket(did)["filings"][1]
    base = {"same": True, "outcome": "UNDECIDED", "quote": f["quote"], "rcp": KT_2, "form": f["form"],
            "due": f["due"], "correction": False, "left": 2, "text": c.dockets[0].latest_text}
    assert direct_vm.run_validator() is True
    assert direct_vm.run_validator(leader_result=dict(base)) is True
    lies = [
        {"same": False, "outcome": "", "quote": ""},         # hides the roll
        {"outcome": "CONFIRMED"}, {"outcome": "DENIED"},     # settles it
        {"due": "2027-12-31"}, {"due": ""},                  # moves the promised date
        {"rcp": KT_3}, {"rcp": "", "left": 0},               # skips a filing
        {"left": 0},                                         # claims the list was read to the end
        {"correction": True},                                # avoids counting the roll
        {"quote": "합병을 최종 결정하였습니다"},               # a sentence that is not in the filing
        {"quote": ""}, {"quote": "당사"},
        {"quote": f["quote"] + " " * 500},
        {"text": base["text"] + " "},                        # what later prompts will be given
        {"extra": 1},
    ]
    for lie in lies:
        assert direct_vm.run_validator(leader_result=dict(base, **lie)) is False, lie
    # quoting another real sentence of the same filing is fine
    other = re.search(r"이와 관련하여[^.]{10,60}", body_text(KT_2)).group(0)
    assert direct_vm.run_validator(leader_result=dict(base, quote=other)) is True
    for junk in (None, [], "ok", {}, 5):
        assert direct_vm.run_validator(leader_result=junk) is False


def test_model_output_is_checked(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    real = sentence(KT_2)
    for bad in ("not json", "{}", json.dumps({"same_rumor": "yes", "outcome": "UNDECIDED", "quote": real}),
                json.dumps({"same_rumor": True, "outcome": "UNDECIDED", "quote": "공시에 없는 문장입니다"}, ensure_ascii=False),
                json.dumps({"same_rumor": True, "outcome": "UNDECIDED", "quote": ""})):
        serve(direct_vm, for_filing(KT_2, bad), today=LAST)
        with direct_vm.expect_revert("[LLM_ERROR]"):
            c.advance(did)
    did2 = opened(direct_vm, c, TK, direct_alice)
    for rcp in TK_ALL[:-1]:
        step(direct_vm, c, did2, rcp, rcp in TK_NEXFLEX)
    serve(direct_vm, for_filing(TK_ALL[-1], answer(TK_ALL[-1], True, "MAYBE")), today=LAST)
    with direct_vm.expect_revert("invalid outcome"):
        c.advance(did2)
    assert c.status(did2)["state"] == "undecided"


def test_incomplete_or_wrong_lists_are_refused(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    path = search_path("00190321", "20260626", LAST)
    page = FX[path].decode("utf-8")
    cases = [
        (re.sub(r"\[총\s*\d+건\]", "[총 250건]", page).encode("utf-8"), "does not fit on one page"),
        (page.replace("00190321", "00164645").encode("utf-8"), "another company"),
        (re.sub(r"\[총\s*\d+건\]", "", page).encode("utf-8"), "no total"),
        (b"<html>maintenance</html>", "no total"),
        ((503, b""), "HTTP 503"),
    ]
    for body, msg in cases:
        serve(direct_vm, override={path: body}, today=LAST)
        with direct_vm.expect_revert(msg):
            c.advance(did)
    good = for_filing(KT_2, answer(KT_2, True))
    serve(direct_vm, good, today=LAST)
    c.advance(did)
    for body, msg in cases:
        err = gl_error(msg)
        serve(direct_vm, good, override={path: body})
        assert direct_vm.run_validator() is False                   # can't confirm what the leader read
        assert direct_vm.run_validator(leader_error=err) is True    # sees the same problem
        assert direct_vm.run_validator(leader_error=Exception("[LLM_ERROR] x")) is False
        serve(direct_vm, good)
        assert direct_vm.run_validator(leader_error=err) is False   # this validator can read the list


def test_long_filing_is_refused_not_cut(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    key = next(k for k in FX if k.startswith(f"/report/viewer.do?rcpNo={KT_2}"))
    big = re.sub(rb"(?i)</td>", ("가" * 21_000).encode("cp949") + b"</td>", FX[key], count=1)
    serve(direct_vm, for_filing(KT_2, answer(KT_2, True)), override={key: big}, today=LAST)
    with direct_vm.expect_revert("longer than 20000"):
        c.advance(did)


def test_a_filing_made_between_leader_and_validator_is_not_agreed(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, KT, direct_alice)
    serve(direct_vm, override=rows_until("00190321", "20260626", "20260723"), today="20260723")
    assert c.advance(did)["read"] == ""                      # as of 07-23 nothing more had been filed
    assert direct_vm.run_validator() is True
    with_new = {search_path("00190321", "20260626", "20260723"): FX[search_path("00190321", "20260626", LAST)]}
    serve(direct_vm, for_filing(KT_2, answer(KT_2, True)), override=with_new, today="20260723")
    assert direct_vm.run_validator() is False


# ---------- money ----------

def test_pot_pays_steps_until_empty_and_the_rest_goes_back(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, TK, direct_alice, pot=FEE * 2 + FEE // 2, fee=FEE)
    paid = [step(direct_vm, c, did, r, r in TK_NEXFLEX, sender=direct_bob)["paid"] for r in TK_ALL[:4]]
    assert paid == [FEE, FEE, FEE // 2, 0]
    direct_vm.sender, direct_vm.value = direct_bob, FEE
    with direct_vm.expect_revert("only the sponsor"):
        c.top_up(did)
    direct_vm.sender = direct_alice
    assert c.top_up(did) == FEE
    direct_vm.value = 0
    with direct_vm.expect_revert("committed until 2027-03-28"):      # promised 2027-02-26, plus 30 days
        c.withdraw(did)
    direct_vm.warp(day("20270329"))
    assert c.withdraw(did) == FEE and c.withdraw(did) == 0


def test_settled_docket_returns_the_pot_to_the_sponsor_only(direct_vm, direct_deploy, direct_alice, direct_bob):
    c = direct_deploy(CONTRACT)
    did = opened(direct_vm, c, PION, direct_alice)
    serve(direct_vm, for_filing(PION_PETITION, answer(PION_PETITION, True, "CONFIRMED")), today=LAST)
    c.close_with(did, PION_PETITION)
    direct_vm.sender = direct_bob
    with direct_vm.expect_revert("only the sponsor"):
        c.withdraw(did)
    direct_vm.sender = direct_alice
    assert c.withdraw(did) == GEN - FEE
    direct_vm.value = 1
    with direct_vm.expect_revert("docket is confirmed"):
        c.top_up(did)
    direct_vm.value = 0
    for call in (lambda: c.mark_silent(did), lambda: c.close_with(did, PION_PETITION), lambda: c.advance(did)):
        with direct_vm.expect_revert("docket is confirmed"):
            call()
    with direct_vm.expect_revert("unknown docket"):
        c.status(99)


def test_open_checks_the_pot(direct_vm, direct_deploy, direct_alice):
    c = direct_deploy(CONTRACT)
    serve(direct_vm, today=LAST)
    direct_vm.sender, direct_vm.value = direct_alice, FEE - 1
    for fee in (FEE, -1):
        with direct_vm.expect_revert("at least one step fee"):
            c.open(KT, fee)
