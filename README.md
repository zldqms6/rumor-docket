# RumorDocket

When a newspaper reports that a Korean listed company is about to merge or sell a unit, the company answers on DART, Korea's filing system, with **미확정**, "undecided", and a date by which it will answer again. Then it files another "undecided". RumorDocket follows one such rumor through every later filing and keeps the answer other contracts can read: confirmed, denied, still undecided (and how often it was pushed back), or silent past the promised date. GenLayer validators each read DART themselves; code reads everything that can be read, and a model only answers whether a filing is about this rumor.

**Contract (Studionet):** [`0x7ae8b273c031fd10e99DbB4F9FeBC1CD32B4b03f`](https://explorer-studio.genlayer.com/address/0x7ae8b273c031fd10e99DbB4F9FeBC1CD32B4b03f) · source sha256 `1d9b6da444c743eed4245ddfb79f3f8ccde5622dfc43212818178bf0224781f2`, checked against the deployed code with [glcheck](https://github.com/zldqms6/glcheck)

## Why I built this

I trade Korean stocks and crypto, and "undecided" filings come up all the time. The sequence rarely changes. On 26 June 2026 KT answered a report about merging KT Cloud: undecided, we will answer within one month. On 24 July: undecided, three months. On 23 October: undecided, six months, so 22 April 2027. One month, three months, six months, and nobody keeps count.

Keeping count by hand is harder than it sounds:
- **Filings of one rumor aren't linked.** Each is a new document with a generic form name. Some list the earlier ones at the bottom under 관련공시, some don't.
- **One company runs several at once.** On 17 November KT filed another "undecided", about KT Cloud raising money. Same company, same subsidiary, same form, different rumor. Taekwang had Nexflex, a shipyard, and then a second auction of the same shipyard going within five months, interleaved.
- **The answer often isn't on the rumor form.** 파이온엑스 (KOSDAQ) answered a bankruptcy rumor with "undecided" in September. The real answer came in October as a petition notice, whose last line says it replaces the earlier reply.
- **Silence looks like nothing.** HMM promised to come back by 6 November on a bulk carrier contract. As of 23 November I find no further reply. There is no filing that says "we didn't file".

Anyone who agrees on something that depends on such a rumor (a finder's fee, a side payment if the deal happens, a lender's covenant) ends up arguing about exactly this. The text needs reading, and whoever reads it has an interest. That is a job for validators.

## How it works

```
open(rcp, step_fee)        payable. rcp = DART receipt number of the first undecided reply
  ├─ must be a rumor reply tagged 미확정, and must not cite an earlier undecided reply
  └─ code reads company, headline, promised date. The GEN sent is the pot.
advance(id)                anyone
  ├─ list of the company's rumor replies since the first one (DART search, must be complete)
  ├─ the OLDEST one this docket has not read. The caller has no say in which.
  ├─ code: form, tag, correction or not, new promised date
  ├─ model: is it about this rumor? if the form has no tag: confirmed, denied or undecided?
  │         must quote a sentence that is literally in the filing
  └─ same rumor + undecided → rolls + 1, new date │ confirmed / denied → settled
     another rumor → recorded and left out        │ nothing unread → "checked" time only
close_with(id, rcp)        anyone names one other filing of the company (petition notice, decision…)
  ├─ filed by the company itself, not a rumor form, not a correction,
  │  not older than the rumor's latest reply, every reply up to that day already read
  └─ model: does it settle this rumor? yes → settled. no → recorded, can't be tried again
mark_silent(id)            anyone, from the 4th day after the promised date: no unread reply on the
                           list → silent. Code only. A later answer, or one that turns out to
                           have been filed in time under another form, takes it out again.
withdraw(id)               sponsor: the rest of the pot, once settled or 30 days after the date
```

`status(id)` is the part other contracts use:

```python
s = gl.get_contract_at(Address(DOCKET)).view().status(docket_id)
if s["state"] == "confirmed": ...   # pay
elif s["state"] == "denied": ...    # refund
else: ...                           # undecided / silent: s["rolls"], s["due"], s["checked_at"]
```

`checked_at` is when validators last found nothing left to read; `0` means never. A consumer that needs a fresh answer calls `advance` first.

**The pot.** Every filing read pays the caller `step_fee`, whether it turned out to belong to the rumor or not, and so does marking silence. A refused `close_with` and an `advance` that finds nothing pay nothing. Paying the caller is safe because the caller can't influence the result: `advance` picks the filing itself, and a nominated filing is tried only once.

### What is code and what is the model

| | decided by |
|---|---|
| which filing is read next | code: oldest unread receipt number on the company's list |
| the list is complete | code: DART's own total (`[총 N건]`) must equal the rows on the page, every row must carry the company's code, otherwise the call fails |
| rumor reply or not, undecided / denied / confirmed tag, correction | code, from the form name. A tag on the form beats whatever the model says |
| headline, promised date | code, from the filing's table (KOSPI and KOSDAQ/KONEX lay it out differently; a correction prints both the old and the new text, the last one counts) |
| days late, silence | code |
| is this filing about this rumor | **model** |
| outcome of an untagged reply or a nominated filing | **model** |

### What a validator agrees to

A result is stored when a majority of the validators vote for it (on Studionet, 3 of 5; the rest show as `IDLE` once a majority is in). Each validator fetches the list and the filing itself, reads them with the same code, asks its own model, and votes yes only if **everything** matches what the leader reported: the receipt number, the form, the promised date, the correction flag, how many filings are left, the filing's full text, "same rumor" and the outcome. There is no tolerance anywhere. The one thing that may differ is which sentence the model quoted; then the leader's quote must be in the text the validator fetched.

If models disagree, nothing is stored and the call can be repeated. If DART gets a new filing between the leader's read and a validator's, they disagree too. Errors are tagged: `[EXPECTED]` and `[EXTERNAL]` must match word for word, `[TRANSIENT]` (DART not answering) and `[LLM_ERROR]` only in kind.

## Live run (Studionet, 2026-11-23, real filings)

`scripts/live_demo.mjs` replayed four real rumors. Every transaction, vote and retry is in [`demo_result.json`](demo_result.json).

| Docket | Call | Filing read | Validators | State after | |
|---|---|---|---|---|---|
| KT's third reply, [2026-10-23](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261023800988) | `open` | refused: this filing refers to an earlier undecided reply: open the docket on the first one | 3 agree on the error | no docket | [tx](https://explorer-studio.genlayer.com/tx/0x8a694b41edbf68b853c44cb31a7aa7adeabbb6be80e3b51b519f47d14c42b80e) |
| **#0 KT**, "KT Cloud merger" | `open` | [2026-06-26](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260626800212) | 3 agree | undecided, due 2026-07-24 | [tx](https://explorer-studio.genlayer.com/tx/0x1bdc13618992259ca543e5e9394bf59fc87ba239040f22a464c3b52dcf244da2) |
| | `advance` | [2026-07-24](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260724800564) this rumor | 3 agree | undecided, rolls 1, due 2026-10-23 | [tx](https://explorer-studio.genlayer.com/tx/0x541566fbe03d5298fd2b35affb52fd78d8493684d56e205a5345e74975df3c6c) |
| | `advance` | [2026-10-23](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261023800988) this rumor | 3 agree | undecided, rolls 2, due 2027-04-22 | [tx](https://explorer-studio.genlayer.com/tx/0x43bd002986e834005ecf022aedbce8a97db98e7d5d5a0d9da9dd35931c025baa) |
| | `advance` | [2026-11-17](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261117800141) other rumor | 3 agree | unchanged | [tx](https://explorer-studio.genlayer.com/tx/0x26f281538a771d6cec848dc5614de31fcc034a1b819ad0e44a7edeb646b354c2) |
| | `advance` | nothing unread | 3 agree | checked | [tx](https://explorer-studio.genlayer.com/tx/0x086e6de494432f5fdb60ac9d0840212ea536d8fcbc39638b941db082f9fb1d4c) |
| **#1 파이온엑스**, creditor's bankruptcy petition | `open` | [2026-09-29](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260929900633) | 3 agree | undecided, due 2026-10-29 | [tx](https://explorer-studio.genlayer.com/tx/0xb68b65768d4ed2cef4630464c4516aac5b28f61e7dcd10e7295118d35be8a833) |
| | `close_with` | [2026-10-19](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261019900583) this rumor<br>“-당사는 2026.09.28 조회공시요구(풍문 또는 보도)에 대한 답변으로 '파산신청서 등 관련문서 등을 송달받지 못한 사유'로 미확정 답변을 하였으나, 본 공시를 2026.09.29. 조회공시요구…” | 3 agree | **confirmed** | [tx](https://explorer-studio.genlayer.com/tx/0x82abe68d6dfe417cc5cc8c5ce3f371c99d65e6571f5fefc8868f78140f8a81a0) |
| | `withdraw` | - | 3 agree | pot returned | [tx](https://explorer-studio.genlayer.com/tx/0xa7f0c80ed22b2f6836c1da6fb3fe7bf7f5046f3b44ce78078c3a42fd9f087717) |
| **#2 HMM**, long-term bulk carrier contract | `open` | [2026-07-09](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260709800131) | 3 agree | undecided, due 2026-08-07 | [tx](https://explorer-studio.genlayer.com/tx/0xa9667bf0d62d854f9e4a48833c40a6cc2a4120190ce7b363246bdc8a55fa4cf7) |
| | `advance` | [2026-08-07](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260807800131) this rumor | 3 agree | undecided, rolls 1, due 2026-11-06 | [tx](https://explorer-studio.genlayer.com/tx/0xfc4edbae1ce3c3566911cc3108ddf74b54a0e1707145f95930718c4c97da56ac) |
| | `close_with` | [2026-10-15](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20261015800543) does not settle it | 3 agree | unchanged | [tx](https://explorer-studio.genlayer.com/tx/0xb4d0cc5ed9a7255f3197f7b7dea8b3f76a34f74b6d36f42bd767bf0c29983423) |
| | `mark_silent` | no unread reply on the list | 3 agree | **silent** (promised 2026-11-06) | [tx](https://explorer-studio.genlayer.com/tx/0x6103efafb29709b3b87e106902a2844c2be26e66e1f72782a2e8be10b7c49c1e) |
| **#3 Taekwang**, buying Nexflex | `open` | [2026-05-04](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260504800294) | 3 agree | undecided, due 2026-06-02 | [tx](https://explorer-studio.genlayer.com/tx/0xcdce07e2d3ca318a36fd6883356209afb8e3c0974dc84af449a280e68f05147f) |
| | `advance` | [2026-06-02](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260602800382) this rumor | 3 agree | undecided, rolls 1, due 2026-09-01 | [tx](https://explorer-studio.genlayer.com/tx/0xba0a2789c0d16d6fa36a74e0ccd6b0bc0aa143f16a0736f29391ae7504269cda) |
| | `advance` | [2026-06-10](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260610800321) other rumor | 3 agree | unchanged | [tx](https://explorer-studio.genlayer.com/tx/0x14ac30a6a8829d9319e8297c48b4771b878bd463454b905d94405858e054bfe5) |
| | `advance` | [2026-06-22](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260622800276) other rumor | 3 agree | unchanged | [tx](https://explorer-studio.genlayer.com/tx/0x19264d19d244c44cb5b7cd76a1d96300475432afb2ff3ec3fd8644eec74159e3) |
| | `advance` | [2026-09-01](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260901800368) this rumor | 3 agree | undecided, rolls 2, due 2027-02-26 | [tx](https://explorer-studio.genlayer.com/tx/0x4ad51090a92d587dcec67f42e45ca8ac8fbfb0f5eb2169a251af74c6ebe5454e) |
| | `advance` | [2026-09-07](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260907800332) other rumor | 3 agree | unchanged | [tx](https://explorer-studio.genlayer.com/tx/0x62a56cf063a5a02fc78c2229f94bf60d6fb065710ed86f20beac42ec7fb1bf03) |
| | `advance` | [2026-09-11](https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260911800691) this rumor<br>“당사는 넥스플렉스 입찰 관련하여 다양한 관점에서 검토하였으나 최종적으로 참여하지 않는 것으로 결정하였습니다.” | 3 agree | **denied** | [tx](https://explorer-studio.genlayer.com/tx/0x7a339f0077ee688c560dec4d4c99897bfd1207f45e187bc8fae67dddacb3444b) |
| | `withdraw` | - | 4 agree | pot returned | [tx](https://explorer-studio.genlayer.com/tx/0x78dca4c366a0dc98b83493f4f83e056d022a2093561363ab3fd45be0265a64fc) |

What it shows:
- **KT.** Two rolls, the date moved from 2026-07-24 to 2026-10-23 to 2027-04-22, and the November filing about KT Cloud raising money was left out: same company, same subsidiary, same form.
- **Taekwang.** Three filings about the shipyard sat between the Nexflex ones and were left out, including one that itself says "not decided" and one untagged one that reports the end of talks. The untagged filing of 09-11 ended this rumor as denied ("finally decided not to take part").
- **파이온엑스.** The answer came as a petition notice, ten days before the promised date, with the sentence that it replaces the September reply.
- **HMM.** The nominated filing is real and large (2.17 trillion won) but buys container ships, and the rumor was about a bulk carrier contract. Refused, unpaid, and it can't be tried again. After that the list had nothing unread and the promised date was 17 days gone.
- All 21 transactions were decided on the first attempt (20 applied, 1 refused as it should be). No model disagreement and no rate limit came up in this run, so the disagreement paths are shown only by the tests.

## API

| method | who | |
|---|---|---|
| `open(rcp, step_fee)` payable | anyone | `{id, company, headline, due}`. One docket per first filing |
| `advance(id)` | anyone | `{read, same_rumor, outcome, state, due, left, paid}`; `read` is `""` if nothing was unread |
| `close_with(id, rcp)` | anyone | `{settles, outcome, state, paid}` |
| `mark_silent(id)` | anyone | `{state, due, paid}` |
| `top_up(id)` payable, `withdraw(id)` | sponsor | |
| `status(id)` | view | `{state, due, rolls, days_late, silent_count, latest_rcp, checked_at}` |
| `get_docket(id)` | view | the above plus company, headline, pot and `filings`: every filing read, with kind, same, outcome, promised date, days late and the quote |
| `find(rcp)`, `dockets_of(corp)`, `get_count()` | view | |

## Tests

```
py -3.12 -m venv .venv && .venv/Scripts/pip install -r requirements-test.txt
python -X utf8 -m pytest -q tests        # -X utf8: the contract source contains Korean
```

22 tests in gltest direct mode. The filing bodies are DART's own pages, byte for byte (MS949). The search pages hold the real rows put back into DART's row markup, because DART cut my address off before I had saved those pages whole; the contract's own reading of them was checked live (above). Each guard was also removed one at a time to see a test fail. They cover the four rumors above, and:
- **a lying leader**: every single field changed (hidden roll, different outcome, moved date, skipped filing, "nothing left", a made-up quote, an altered text, extra fields, junk) is voted down, while quoting a different real sentence is accepted;
- **a validator that disagrees**: other outcome, other rumor, a model that answers garbage, one more filing on its list;
- lists that are incomplete, belong to another company, have no total, or come back as an error page, seen by the leader only or by both;
- a filing longer than 20,000 characters is refused, not cut; a tag beats the model; a same-day correction isn't a roll;
- the caller can't skip a filing, can't retry a refused one, can't mark silence over an unread reply;
- pot accounting down to the last fraction, withdrawal dates, who may do what.

## Limits

- **"Silent" is not an accusation.** It says that DART's list had no further rumor reply from the company by three days after the date it named. The company may have answered under another form (then `close_with` fixes the record) or may have been excused. Three days cover a weekend, not a Chuseok week.
- **Only one-page exchange forms can be read.** Reports filed on DART's own multi-page form (주요사항보고서, for example a full merger report) are refused by `close_with`. Most decisions also come as an exchange form; not all.
- **Rumor forms only.** Replies to unusual price moves (현저한 시황변동), which often say "undecided" about several things at once, are not followed.
- **The first filing is the sponsor's choice.** A filing that cites an earlier undecided reply is refused, but some don't cite it, so a docket can start in the middle of a story. The filings before it are then simply not in it.
- **Same-day order** is by receipt number. A reply numbered lower than the opening one on the same day is treated as earlier.
- **A filing models can't agree on blocks the docket**, since filings are read in order. Nothing wrong is stored, but it stops there; the sponsor's pot frees up 30 days after the promised date.
- **At most 100 rumor filings per docket.** The busiest company I found had 13 in six months.
- **DART throttles.** While collecting test data I sent it roughly 200 requests within a few minutes and my own address was cut off. One step costs three requests per validator; the live run kept 45 seconds between transactions and met no refusal.
- Studionet, test GEN. The contract has not been audited.
