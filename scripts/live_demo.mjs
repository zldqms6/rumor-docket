// Live run on Studionet against real DART filings.
//   node scripts/live_demo.mjs <contractAddress> [resume]
// Replays four real rumors from the filings as they stand on DART today:
//   KT Cloud merger          two rolls, then a funding rumor that must be left out
//   Taekwang / Nexflex       two rolls between two other rumors, ends in a denial
//   PIONX bankruptcy rumor   answered by a petition notice, not by a rumor form
//   HMM bulk contract        an unrelated investment decision is nominated and must be
//                            refused, then the promised date has passed without a reply
// and one filing that can't start a docket. Sponsor and keeper are demo keys. Results
// go to demo_result.json; "resume" continues from it. DART drops callers that come too
// fast, so there is a pause between transactions.
import { createClient, createAccount, generatePrivateKey } from "genlayer-js";
import { studionet } from "genlayer-js/chains";
import { TransactionStatus } from "genlayer-js/types";
import fs from "node:fs";

const [address, mode] = process.argv.slice(2);
const GEN = 10n ** 18n;
const FEE = GEN / 10n;
const OUT = "demo_result.json";
const PAUSE = 45_000;

function key(name) {
  const env = fs.existsSync(".env") ? fs.readFileSync(".env", "utf8") : "";
  const m = env.match(new RegExp(`^${name}=(0x[0-9a-f]+)`, "m"));
  if (m) return m[1];
  const pk = generatePrivateKey();
  fs.appendFileSync(".env", `${name}=${pk}\n`);
  return pk;
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const now = () => Math.floor(Date.now() / 1000);

// Studionet sometimes answers with an HTML error page instead of JSON.
async function retry(label, fn, tries = 6) {
  for (let i = 1; ; i++) {
    try {
      return await fn();
    } catch (e) {
      if (i >= tries) throw e;
      console.log(`  ${label} failed (${(e.shortMessage ?? e.message).slice(0, 120)}), retry ${i}`);
      await sleep(15_000 * i);
    }
  }
}
async function fund(addr) {
  await retry("fund", async () => {
    const res = await fetch(studionet.rpcUrls.default.http[0], {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ jsonrpc: "2.0", id: 1, method: "sim_fundAccount", params: [addr, Number(100n * GEN)] }),
    });
    const body = JSON.parse(await res.text());
    if (body.error) throw new Error(JSON.stringify(body.error));
  });
}

const sponsor = createAccount(key("DEMO_SPONSOR_PK"));
const keeper = createAccount(key("DEMO_KEEPER_PK"));
const gl = createClient({ chain: studionet });

const plain = (v) => JSON.parse(JSON.stringify(v, (_, x) => (typeof x === "bigint" ? x.toString() : x instanceof Map ? Object.fromEntries(x) : x)));
const read = (functionName, args) =>
  retry(`read ${functionName}`, async () =>
    plain(await gl.readContract({ address, functionName, args, transactionHashVariant: "latest-nonfinal" })));

// A write can come back ACCEPTED while the leader errored (validators agreed on the error),
// so keep the leader's execution result and the votes, not just the status. Rate limits and
// DART connection errors are retried; every attempt is kept in the result file.
async function write(account, functionName, args, value = 0n) {
  const attempts = [];
  for (let attempt = 1; attempt <= 5; attempt++) {
    await sleep(PAUSE);
    const hash = await retry(`send ${functionName}`, () => gl.writeContract({ account, address, functionName, args, value }));
    const r = await retry(`receipt ${hash}`, () =>
      gl.waitForTransactionReceipt({ hash, status: TransactionStatus.ACCEPTED, retries: 150, interval: 8000 }));
    const leader = r?.consensus_data?.leader_receipt?.[0];
    const exec = leader?.execution_result;
    const err = leader?.genvm_result?.error_code;
    const votes = r?.last_round?.validator_votes_name ?? null;
    const payload = leader?.result?.payload;
    const msg = typeof payload === "string" ? payload : JSON.stringify(plain(payload ?? ""));
    console.log(`${functionName}(${args.join(", ")}) -> ${hash} ${r?.status_name ?? ""} ${exec ?? ""} ${err ?? ""} ${votes ? votes.join(",") : ""} ${exec === "ERROR" ? msg.slice(0, 160) : ""}`);
    const one = { hash, status: r?.status_name, exec, error: err ?? null, votes, message: String(msg).slice(0, 600) };
    attempts.push(one);
    const again = r?.status_name === "UNDETERMINED" || (exec === "ERROR" && (err === "LLM_RATE_LIMITED" || /TRANSIENT|LLM_ERROR/.test(msg)));
    if (!again) return { ...one, attempts };
    await sleep(60_000 * attempt);
  }
  return { ...attempts.at(-1), attempts, gave_up: true };
}

const PLAN = [
  { label: "refused-opening", rcp: "20261023800988", steps: [] },   // KT's third reply, not the first
  { label: "kt-cloud-merger", rcp: "20260626800212", steps: ["advance", "advance", "advance", "advance"] },
  { label: "pionx-petition", rcp: "20260929900633", steps: [["close_with", "20261019900583"], "withdraw"] },
  { label: "hmm-bulk-contract", rcp: "20260709800131", steps: ["advance", ["close_with", "20261015800543"], "mark_silent"] },
  { label: "taekwang-nexflex", rcp: "20260504800294", steps: ["advance", "advance", "advance", "advance", "advance", "advance", "withdraw"] },
];

const out = mode === "resume" ? JSON.parse(fs.readFileSync(OUT, "utf8"))
  : { contract: address, network: "studionet", created: now(), dockets: [] };
const save = () => fs.writeFileSync(OUT, JSON.stringify(out, null, 2));
if (mode !== "resume") for (const a of [sponsor, keeper]) await fund(a.address);

for (const p of PLAN) {
  let d = out.dockets.find((x) => x.label === p.label);
  if (!d) {
    const open = await write(sponsor, "open", [p.rcp, FEE], GEN);
    d = { label: p.label, rcp: p.rcp, id: Number(await read("find", [p.rcp])), open, steps: [] };
    out.dockets.push(d);
    save();
  }
  if (d.id < 0) continue;
  for (const s of p.steps.slice(d.steps.length)) {
    const [fn, ...rest] = Array.isArray(s) ? s : [s];
    const tx = await write(fn === "withdraw" ? sponsor : keeper, fn, [d.id, ...rest]);
    const state = await read("get_docket", [d.id]);
    const last = state.filings.at(-1);
    console.log(`   ${p.label}: ${state.state} rolls ${state.rolls} due ${state.due} | ${last.rcp} same=${last.same} ${last.outcome} | ${last.quote.slice(0, 80)}`);
    d.steps.push({ step: fn, tx, after: { state: state.state, rolls: state.rolls, due: state.due, silent: state.silent_count, pot: state.pot, last } });
    d.final = state;
    save();
    if (tx.gave_up) break;
  }
}
out.finished = now();
save();
