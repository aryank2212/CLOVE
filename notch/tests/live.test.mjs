// Live activities (src/core/live.ts): the order they take the pill in, and
// the parsers behind them — notifications, durations, quotes, scores, routes.

import test from "node:test";
import assert from "node:assert/strict";

const {
  LiveStore, classifyNotification, clock, decodePolyline, findEta, findOtp, fmtDistance, fmtMoney, followedMatches,
  mergeStage, navRemaining, parseBars, parseDuration, parseQuote, parseRoute, parseScoreboard, quoteCandidates,
  shortScore, timerLeft,
} = await import("../src/core/live.ts");

const note = (app, summary, body = "") => classifyNotification({ id: 1, app, summary, body }, 1000);

test("the most urgent activity takes the pill, the next one the bubble", () => {
  const live = new LiveStore();
  const media = { bus: "b", app: "Spotify", source: "spotify", title: "t", artist: "", album: "", artUrl: null, duration: 100, position: 0, positionAt: 0, playing: true, canNext: true, canPrev: true, canSeek: true };
  live.upsert("media", "media", media, 1);
  live.upsert("stock:TSLA", "stock", { symbol: "TSLA", code: "TSLA", name: "Tesla", price: 1, change: 0, changePct: 0, currency: "USD", series: [], prevClose: 1, marketOpen: true }, 2);
  assert.equal(live.primary(10).id, "media");
  live.upsert("t1", "timer", { label: "Tea", duration: 300, endsAt: 400_000, pausedLeft: null, done: false }, 3);
  assert.equal(live.primary(10).id, "t1");
  assert.equal(live.secondary(10).id, "media");
  live.upsert("call", "call", { name: "Mom", number: "", app: "Phone", state: "incoming", video: false, since: 4 }, 4);
  assert.equal(live.primary(10).id, "call");
  // Paused music steps behind everything still going on.
  live.patch("media", "media", { playing: false }, 5);
  assert.deepEqual(live.ranked(10).map((a) => a.id), ["call", "t1", "stock:TSLA", "media"]);
});

test("an activity leaves when its time is up, and focus follows", () => {
  const live = new LiveStore();
  live.upsert("auth", "auth", { method: "face", ok: true, detail: "" }, 100, 2000);
  live.focusId = "auth";
  assert.equal(live.prune(2000), false);
  assert.equal(live.prune(2100), true);
  assert.equal(live.size, 0);
  assert.equal(live.focusId, null);
});

test("a timer that rings outranks a call that is over", () => {
  const live = new LiveStore();
  live.upsert("call", "call", { name: "x", number: "", app: "Phone", state: "missed", video: false, since: 1 }, 1);
  live.upsert("t", "timer", { label: "Tea", duration: 60, endsAt: 0, pausedLeft: null, done: true }, 2);
  assert.equal(live.primary(5).id, "t");
  assert.equal(timerLeft({ label: "", duration: 60, endsAt: 31_000, pausedLeft: null, done: false }, 1000), 30);
  assert.equal(timerLeft({ label: "", duration: 60, endsAt: 0, pausedLeft: 12, done: false }, 1000), 12);
});

test("durations are read the way people write them", () => {
  assert.equal(parseDuration("5m"), 300);
  assert.equal(parseDuration("1h 30m"), 5400);
  assert.equal(parseDuration("90s"), 90);
  assert.equal(parseDuration("2:30"), 150);
  assert.equal(parseDuration("1:00:05"), 3605);
  assert.equal(parseDuration("10 minutes"), 600);
  assert.equal(parseDuration("an hour"), 3600);
  assert.equal(parseDuration("25"), 1500);
  assert.equal(parseDuration("soon"), null);
  assert.equal(clock(65), "1:05");
  assert.equal(clock(3725), "1:02:05");
});

test("a ride is followed from its notifications", () => {
  const r = note("Uber", "Uber", "Ramesh Kumar is arriving in 3 mins in a white Swift DL 01 AB 1234. Your PIN is 4821");
  assert.equal(r.kind, "ride");
  assert.equal(r.id, "ride:uber");
  assert.deepEqual([r.data.stage, r.data.eta, r.data.driver, r.data.otp, r.data.vehicle], [1, "3 min", "Ramesh Kumar", "4821", "DL 01 AB 1234"]);
  assert.equal(note("Ola", "Your driver has arrived", "Share OTP 9912").data.stage, 2);
  assert.equal(note("Rapido", "Ride started", "Enjoy your ride").data.stage, 3);
  assert.equal(note("Rapido", "Trip completed", "Rate your captain").data.stage, 4);
  // An advert is not a ride.
  assert.equal(note("Uber", "50% off your next 3 rides", "Use code SAVE50"), null);
  assert.equal(note("Uber", "Trip cancelled", "Your driver cancelled").kind, "cancel");
});

test("an order is followed from its notifications", () => {
  assert.equal(note("Zepto", "Order confirmed", "We have received your order").data.stage, 0);
  const packed = note("Zepto", "Your order is packed", "Arriving in 8 minutes");
  assert.deepEqual([packed.data.stage, packed.data.eta], [1, "8 min"]);
  const out = note("Blinkit", "Order out for delivery", "Noman is on the way with your order and will arrive by 2:15 pm");
  assert.deepEqual([out.id, out.data.stage, out.data.eta, out.data.courier], ["delivery:blinkit", 2, "2:15 pm", "Noman"]);
  assert.equal(note("Amazon Shopping", "Shipped", "Your package arrives tomorrow").data.eta, "Tomorrow");
  assert.equal(note("Flipkart", "Delivered", "Your order has been delivered").data.stage, 3);
  assert.equal(note("Swiggy", "Instamart", "Your Instamart order is out for delivery").id, "delivery:instamart");
  assert.equal(note("KDE Connect", "Uber Eats", "Your order is being prepared").id, "delivery:ubereats");
  assert.equal(note("Amazon", "Deals of the day", "Up to 70% off electronics"), null);
});

test("a later message never moves an order backwards, and keeps what was known", () => {
  const out = { brand: "zepto", stage: 2, eta: "5 min", courier: "Ravi", otp: "1234", text: "out" };
  const late = { brand: "zepto", stage: 1, eta: "", courier: "", otp: "", text: "packed" };
  assert.deepEqual(mergeStage(out, late), out);
  const done = mergeStage(out, { brand: "zepto", stage: 3, eta: "", courier: "", otp: "", text: "delivered" });
  assert.deepEqual([done.stage, done.courier, done.eta], [3, "Ravi", ""]);
});

test("payments are told from offers and reminders", () => {
  const paid = note("Google Pay", "Payment successful", "You paid ₹450.00 to Zomato Ltd using UPI");
  assert.deepEqual([paid.kind, paid.data.amount, paid.data.currency, paid.data.direction, paid.data.party], ["payment", 450, "INR", "paid", "Zomato Ltd"]);
  const sms = note("Messages", "HDFC Bank", "Rs.1,250.50 debited from a/c XX1234 to AMAZON PAY on 10-11-26");
  assert.deepEqual([sms.data.amount, sms.data.direction, sms.data.party], [1250.5, "paid", "AMAZON PAY"]);
  const got = note("PhonePe", "Money received", "Received ₹2,000 from Rahul Verma");
  assert.deepEqual([got.data.direction, got.data.amount, got.data.party], ["received", 2000, "Rahul Verma"]);
  assert.equal(note("Paytm", "Offer", "Get ₹100 cashback offer on recharge"), null);
  assert.equal(note("Bank", "Reminder", "Your bill is due: pay ₹999 now"), null);
  assert.equal(fmtMoney(450, "INR"), "₹450");
  assert.equal(fmtMoney(378.05, "USD"), "$378.05");
  assert.equal(fmtMoney(125000, "INR"), "₹1,25,000");
});

test("calls are recognised with who is calling", () => {
  const c = note("WhatsApp", "Priya Sharma", "Incoming video call");
  assert.deepEqual([c.kind, c.data.name, c.data.state, c.data.video], ["call", "Priya Sharma", "incoming", true]);
  const t = note("Telegram", "Incoming call", "Rahul");
  assert.deepEqual([t.data.name, t.data.video], ["Rahul", false]);
  assert.equal(note("Phone", "Missed call", "Mom").data.state, "missed");
  assert.equal(note("Slack", "Rahul", "let's call it a day"), null);
});

test("times, codes and distances are picked out of text", () => {
  assert.equal(findEta("arriving in 10-15 mins"), "15 min");
  assert.equal(findEta("will reach by 7.45 PM"), "7:45 pm");
  assert.equal(findEta("Arriving 12 Nov"), "12 Nov");
  assert.equal(findOtp("Your OTP is 482913"), "482913");
  assert.equal(findOtp("5521 is your PIN for the ride"), "5521");
  assert.equal(findOtp("Order #482913 placed"), "");
  assert.equal(fmtDistance(300), "300 m");
  assert.equal(fmtDistance(4200), "4.2 km");
  assert.equal(fmtDistance(42_000), "42 km");
});

test("a typed symbol becomes the codes to ask for", () => {
  assert.deepEqual(quoteCandidates("tsla"), ["TSLA", "TSLA-IN"]);
  assert.deepEqual(quoteCandidates("RELIANCE.NS"), ["RELIANCE-IN"]);
  assert.deepEqual(quoteCandidates("NSE:INFY"), ["INFY-IN"]);
  assert.deepEqual(quoteCandidates("nifty"), [".NSEI"]);
  assert.deepEqual(quoteCandidates("btc"), ["BTC.CM="]);
  assert.deepEqual(quoteCandidates("ETH-USD"), ["ETH.CM="]);
  assert.deepEqual(quoteCandidates(""), []);
});

test("a quote and its bars become the stock card", () => {
  const q = parseQuote({ symbol: "TSLA", code: 0, name: "Tesla Inc", last: "1,378.05", change: "+19.83", change_pct: "+5.54%", currencyCode: "USD", curmktstatus: "REG_MKT", previous_day_closing: "1,358.22" }, "TSLA");
  assert.deepEqual([q.price, q.change, q.changePct, q.prevClose, q.marketOpen], [1378.05, 19.83, 5.54, 1358.22, true]);
  assert.equal(parseQuote({ symbol: ".BSESN", code: 3 }, "SENSEX"), null);
  const bars = { barData: { priceBars: Array.from({ length: 200 }, (_, i) => ({ close: String(100 + i) })) } };
  const series = parseBars(bars, 50);
  assert.equal(series.length, 50);
  assert.equal(series[0], 100);
  assert.equal(series[49], 299);
  assert.deepEqual(parseBars(null), []);
});

test("a scoreboard is read, and only followed teams come through", () => {
  const json = { sports: [{ leagues: [{ name: "Indian Premier League", shortName: "IPL", events: [
    { id: "1", date: "2026-11-10T14:00:00Z", summary: "MI need 24", fullStatus: { type: { state: "in", shortDetail: "18.2 ov" } }, competitors: [
      { abbreviation: "MI", displayName: "Mumbai Indians", score: "182/4 (18.2 ov)", homeAway: "home" },
      { abbreviation: "CSK", displayName: "Chennai Super Kings", score: "205/6", homeAway: "away", winner: false }] },
    { id: "2", date: "2026-11-11T14:00:00Z", status: "pre", competitors: [
      { abbreviation: "RCB", displayName: "Royal Challengers", score: "" }, { abbreviation: "KKR", displayName: "Kolkata", score: "" }] },
  ] }] }] };
  const all = parseScoreboard(json, "cricket");
  assert.equal(all.length, 2);
  assert.deepEqual([all[0].state, all[0].home.abbr, all[0].away.score, all[0].status], ["in", "MI", "205/6", "18.2 ov"]);
  assert.deepEqual(followedMatches(all, ["mi"]).map((m) => m.eventId), ["1"]);
  assert.deepEqual(followedMatches(all, ["Kolkata", "Mumbai"]).map((m) => m.eventId), ["1", "2"]);
  assert.deepEqual(followedMatches(all, []), []);
  assert.equal(shortScore("182/4 (18.2 ov)"), "182/4");
  assert.equal(shortScore("336 & 318/4d"), "318/4d");
  assert.equal(shortScore(""), "–");
});

test("a route becomes steps, a line and a time of arrival", () => {
  assert.deepEqual(decodePolyline("_p~iF~ps|U_ulLnnqC_mqNvxq`@"), [[-120.2, 38.5], [-120.95, 40.7], [-126.453, 43.252]]);
  const json = { routes: [{ distance: 1200, duration: 300, geometry: "_p~iF~ps|U_ulLnnqC_mqNvxq`@", legs: [{ steps: [
    { name: "Kartavya Path", distance: 300, maneuver: { type: "depart", modifier: "straight" } },
    { name: "C-Hexagon", distance: 900, maneuver: { type: "turn", modifier: "left" } },
    { name: "", distance: 0, maneuver: { type: "arrive" } },
  ] }] }] };
  const nav = parseRoute(json, "Home", "India Gate", 1000);
  assert.deepEqual(nav.steps.map((s) => s.text), ["Head out on Kartavya Path", "Turn left onto C-Hexagon", "You have arrived"]);
  assert.deepEqual(nav.steps.map((s) => s.modifier), ["straight", "left", "arrive"]);
  assert.equal(nav.etaAt, 301_000);
  assert.equal(nav.line.length, 3);
  assert.equal(navRemaining({ ...nav, stepIndex: 1 }), 900);
  assert.equal(parseRoute({ routes: [] }, "a", "b", 0), null);
});
