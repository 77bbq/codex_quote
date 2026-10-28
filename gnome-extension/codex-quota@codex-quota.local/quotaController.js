/* exported QuotaController */
'use strict';

const DefaultModel = typeof module !== 'undefined' ? require('./quotaModel.js') : null;

// The adapter owns Shell/Gio resources; keeping scheduling here makes disable races testable.
var QuotaController = class {
    constructor(adapter, config, model) {
        this.adapter = adapter;
        this.config = config;
        this.model = model || DefaultModel;
        this.state = {snapshot: null, error: null, busy: false, low: false};
        this.enabled = false;
        this.generation = 0;
        this.timer = null;
        this.request = null;
    }

    enable() {
        if (this.enabled)
            return;
        this.enabled = true;
        this.generation++;
        this.refresh();
    }

    refresh() {
        if (!this.enabled || this.state.busy)
            return;
        if (this.timer !== null) {
            this.adapter.cancelTimer(this.timer);
            this.timer = null;
        }
        this.state = Object.assign({}, this.state, {busy: true});
        this.adapter.render(this.state, false);
        const generation = this.generation;
        let finished = false;
        const complete = (snapshot, error) => {
            if (finished)
                return;
            finished = true;
            if (!this.enabled || generation !== this.generation)
                return;
            this.request = null;
            let notifyLow = false;
            try {
                if (error)
                    throw new Error(String(error));
                const next = this.model.applySuccess(this.state, this.model.validateSnapshot(snapshot), this.config.threshold);
                this.state = next.state;
                notifyLow = next.notifyLow;
            } catch (failure) {
                this.state = this.model.applyFailure(this.state, failure.message);
            }
            this.adapter.render(this.state, notifyLow);
            this.timer = this.adapter.schedule(this.config.interval, () => {
                this.timer = null;
                this.refresh();
            });
        };
        try {
            const handle = this.adapter.launch(complete);
            if (!finished)
                this.request = handle;
        } catch (error) {
            complete(null, error.message);
        }
    }

    disable() {
        this.enabled = false;
        this.generation++;
        if (this.timer !== null)
            this.adapter.cancelTimer(this.timer);
        this.timer = null;
        if (this.request)
            this.request.cancel();
        this.request = null;
        this.state = Object.assign({}, this.state, {busy: false});
    }
};

if (typeof module !== 'undefined')
    module.exports = {QuotaController};
