'use strict';
const assert = require('assert');
const {QuotaController} = require('../gnome-extension/codex-quota@codex-quota.local/quotaController.js');
const Model = require('../gnome-extension/codex-quota@codex-quota.local/quotaModel.js');

function data(value) {
    return {schemaVersion: 1, updatedAt: '2026-10-28T15:30:00+08:00', summaryRemaining: value,
        buckets: [{id: 'codex', name: 'Codex', windows: [{id: 'primary', remaining: value,
            durationMins: 300, resetsAt: null}], credits: null}], resetCredits: null};
}

const jobs = [], timers = new Map(), rendered = [];
let nextTimer = 1;
const adapter = {
    launch(done) {
        const job = {done, cancelled: false};
        jobs.push(job);
        return {cancel() { job.cancelled = true; }};
    },
    schedule(seconds, run) {
        assert.strictEqual(seconds, 120);
        const id = nextTimer++;
        timers.set(id, run);
        return id;
    },
    cancelTimer(id) { timers.delete(id); },
    render(state, notify) { rendered.push({text: Model.summaryText(state), busy: state.busy, notify, state}); },
};
const controller = new QuotaController(adapter, {interval: 120, threshold: 20});
controller.enable();
assert.strictEqual(jobs.length, 1);
assert.strictEqual(rendered.at(-1).text, 'Codex …');
controller.refresh();
assert.strictEqual(jobs.length, 1, 'concurrent refresh must not start another query');
jobs[0].done(data(72), null);
assert.strictEqual(rendered.at(-1).text, 'Codex 72%');
assert.strictEqual(timers.size, 1);
controller.refresh();
assert.strictEqual(timers.size, 0, 'manual refresh replaces the scheduled refresh');
jobs[1].done(null, '网络不可用');
assert.strictEqual(rendered.at(-1).text, 'Codex 72% !');
assert.strictEqual(rendered.at(-1).state.snapshot.updatedAt, '2026-10-28T15:30:00+08:00');

controller.refresh();
const late = jobs[2];
const beforeDisable = rendered.length;
controller.disable();
assert.strictEqual(late.cancelled, true);
assert.strictEqual(timers.size, 0);
late.done(data(0), null);
assert.strictEqual(rendered.length, beforeDisable, 'late response cannot recreate disabled UI');
controller.enable();
assert.strictEqual(jobs.length, 4);
late.done(data(0), null);
assert.strictEqual(rendered.at(-1).busy, true, 'an old generation cannot finish a new query');
jobs[3].done(data(10), null);
assert.strictEqual(rendered.at(-1).notify, true);
assert.strictEqual(rendered.at(-1).text, 'Codex 10%');
controller.disable();
assert.strictEqual(timers.size, 0);

// A synchronous launcher failure is presented as an error and still retries later.
const errors = [];
const failing = new QuotaController({...adapter,
    launch() { throw new Error('找不到可执行文件'); },
    render(state) { errors.push(state); },
}, {interval: 120, threshold: 20});
failing.enable();
assert.strictEqual(errors.at(-1).error, '找不到可执行文件');
assert.strictEqual(errors.at(-1).busy, false);
assert.strictEqual(timers.size, 1);
failing.disable();
console.log('Topbar controller: all assertions passed.');
