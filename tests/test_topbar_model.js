'use strict';
const assert = require('assert');
const Model = require('../gnome-extension/codex-quota@codex-quota.local/quotaModel.js');

function snapshot(values = [72, 84]) {
    return {
        schemaVersion: 1,
        updatedAt: '2026-10-28T15:30:00+08:00',
        summaryRemaining: values.filter(v => v !== null).length ? Math.min(...values.filter(v => v !== null)) : null,
        buckets: [{id: 'codex', name: 'Codex', windows: values.map((remaining, i) => ({
            id: i === 0 ? 'primary' : 'secondary', remaining,
            durationMins: i === 0 ? 300 : 10080, resetsAt: null,
        })), credits: null}],
        resetCredits: null,
    };
}

const initial = () => ({snapshot: null, error: null, busy: false, low: false});
const data = Model.validateSnapshot(snapshot());
let outcome = Model.applySuccess(initial(), data, 20);
assert.strictEqual(Model.summaryText(outcome.state), 'Codex 72%');
assert.strictEqual(outcome.notifyLow, false);
assert.strictEqual(Model.durationLabel(300, 0), '5 小时窗口');
assert.strictEqual(Model.durationLabel(10080, 1), '7 天窗口');
assert.strictEqual(Model.durationLabel(90, 0), '90 分钟窗口');
assert.strictEqual(Model.durationLabel(null, 1), '窗口 2');

// A failed refresh must not erase the last successful snapshot or timestamp.
const failed = Model.applyFailure(outcome.state, '网络不可用');
assert.strictEqual(failed.snapshot.updatedAt, '2026-10-28T15:30:00+08:00');
assert.strictEqual(Model.summaryText(failed), 'Codex 72% !');
assert.strictEqual(failed.error, '网络不可用');
assert.strictEqual(Model.summaryText(Model.applyFailure(initial(), '未登录')), 'Codex —');
assert.strictEqual(Model.summaryText({...initial(), busy: true}), 'Codex …');

// Unknown is different from a genuinely exhausted window.
outcome = Model.applySuccess(initial(), Model.validateSnapshot(snapshot([null, null])), 20);
assert.strictEqual(Model.summaryText(outcome.state), 'Codex —');
assert.strictEqual(outcome.notifyLow, false);
outcome = Model.applySuccess(initial(), Model.validateSnapshot(snapshot([0, null])), 20);
assert.strictEqual(Model.summaryText(outcome.state), 'Codex 0%');
assert.strictEqual(outcome.notifyLow, true);

let state = initial();
let notifications = 0;
for (const values of [[10, 84], [10, 84], [72, 84], [10, 84]]) {
    const next = Model.applySuccess(state, Model.validateSnapshot(snapshot(values)), 20);
    notifications += Number(next.notifyLow);
    state = next.state;
    state = Model.applyFailure(state, '临时失败');
}
assert.strictEqual(notifications, 2);

// Unknown data neither displays a fresh low warning nor rearms an old alert.
const lowState = Model.applySuccess(initial(), Model.validateSnapshot(snapshot([10, 84])), 20).state;
const unknownState = Model.applySuccess(lowState, Model.validateSnapshot(snapshot([null, null])), 20).state;
assert.strictEqual(Model.isLow(unknownState.snapshot, 20), false);
assert.strictEqual(Model.isLow(lowState.snapshot, 20), true);
assert.strictEqual(Model.applySuccess(unknownState, Model.validateSnapshot(snapshot([10, 84])), 20).notifyLow, false);

// Multiple groups must participate in the summary.
const groups = snapshot();
groups.buckets.push({id: 'review', name: '代码审查', windows: [{id: 'primary', remaining: 12,
    durationMins: 60, resetsAt: null}], credits: {balance: '12.50', hasCredits: true, unlimited: false}});
groups.summaryRemaining = 12;
assert.strictEqual(Model.summaryText(Model.applySuccess(initial(), Model.validateSnapshot(groups), 20).state), 'Codex 12%');

for (const mutate of [
    d => { d.schemaVersion = 2; },
    d => { d.updatedAt = 'not-a-date'; },
    d => { d.buckets = null; },
    d => { d.buckets[0].windows[0].remaining = false; },
    d => { d.buckets[0].windows[0].remaining = NaN; },
    d => { d.buckets[0].windows[0].remaining = 101; },
    d => { d.buckets[0].windows[0].durationMins = Infinity; },
    d => { d.buckets[0].windows[0].resetsAt = 'tomorrow'; },
    d => { d.summaryRemaining = 99; },
]) {
    const bad = snapshot();
    mutate(bad);
    assert.throws(() => Model.validateSnapshot(bad), Error);
}

const now = new Date(2026, 9, 28, 15, 30).getTime() / 1000;
assert.match(Model.resetLabel(now + 3600, now), /1 小时后/);
assert.match(Model.resetLabel(now - 1, now), /已到重置时间/);
assert.match(Model.resetLabel(null, now), /未知/);
console.log('Topbar model: all assertions passed.');
