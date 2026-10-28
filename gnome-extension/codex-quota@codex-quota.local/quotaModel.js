/* exported validateSnapshot, summaryText, durationLabel, resetLabel, applySuccess,
   applyFailure, formatPercent, isLow */
'use strict';

function _number(value) {
    return typeof value === 'number' && Number.isFinite(value);
}

function _object(value) {
    return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function validateSnapshot(data) {
    const invalid = () => { throw new Error('额度数据格式不正确，请检查程序版本。'); };
    if (!_object(data) || data.schemaVersion !== 1 || typeof data.updatedAt !== 'string' ||
        !Number.isFinite(Date.parse(data.updatedAt)) || !Array.isArray(data.buckets))
        invalid();
    let minimum = null;
    for (const bucket of data.buckets) {
        if (!_object(bucket) || typeof bucket.id !== 'string' || typeof bucket.name !== 'string' ||
            !Array.isArray(bucket.windows))
            invalid();
        for (const window of bucket.windows) {
            if (!_object(window) || !['primary', 'secondary'].includes(window.id))
                invalid();
            if (window.remaining !== null && (!_number(window.remaining) || window.remaining < 0 || window.remaining > 100))
                invalid();
            if (window.durationMins !== null && (!_number(window.durationMins) || window.durationMins <= 0))
                invalid();
            if (window.resetsAt !== null && (!_number(window.resetsAt) ||
                !Number.isFinite(new Date(window.resetsAt * 1000).getTime())))
                invalid();
            if (window.remaining !== null)
                minimum = minimum === null ? window.remaining : Math.min(minimum, window.remaining);
        }
        if (bucket.credits !== null) {
            if (!_object(bucket.credits))
                invalid();
            const balance = bucket.credits.balance;
            if (balance !== null && typeof balance !== 'string' && !_number(balance))
                invalid();
            for (const key of ['hasCredits', 'unlimited']) {
                if (bucket.credits[key] !== null && typeof bucket.credits[key] !== 'boolean')
                    invalid();
            }
        }
    }
    if (data.summaryRemaining !== minimum ||
        (data.resetCredits !== null && (!_number(data.resetCredits) || data.resetCredits < 0)))
        invalid();
    return data;
}

function formatPercent(value) {
    return value === null ? '未知' : `${Number(value.toFixed(1))}%`;
}

function summaryText(state) {
    if (!state.snapshot)
        return state.busy ? 'Codex …' : 'Codex —';
    const value = state.snapshot.summaryRemaining;
    return `Codex ${value === null ? '—' : formatPercent(value)}${state.error ? ' !' : ''}`;
}

function durationLabel(minutes, index) {
    if (!_number(minutes) || minutes <= 0)
        return `窗口 ${index + 1}`;
    if (minutes % 1440 === 0)
        return `${minutes / 1440} 天窗口`;
    if (minutes % 60 === 0)
        return `${minutes / 60} 小时窗口`;
    return `${minutes} 分钟窗口`;
}

function _pad(value) {
    return String(value).padStart(2, '0');
}

function resetLabel(timestamp, now) {
    if (!_number(timestamp))
        return '重置时间未知';
    const date = new Date(timestamp * 1000);
    const absolute = `${date.getMonth() + 1} 月 ${date.getDate()} 日 ${_pad(date.getHours())}:${_pad(date.getMinutes())} 重置`;
    const delta = timestamp - now;
    if (delta <= 0)
        return `${absolute} · 已到重置时间，等待刷新`;
    let relative;
    if (delta < 3600)
        relative = `${Math.ceil(delta / 60)} 分钟后`;
    else if (delta < 86400)
        relative = `${Math.ceil(delta / 3600)} 小时后`;
    else
        relative = `${Math.ceil(delta / 86400)} 天后`;
    return `${absolute} · 约 ${relative}`;
}

function isLow(snapshot, threshold) {
    return snapshot !== null && snapshot.summaryRemaining !== null && snapshot.summaryRemaining <= threshold;
}

function applySuccess(state, snapshot, threshold) {
    const value = snapshot.summaryRemaining;
    const low = isLow(snapshot, threshold);
    // An unknown value is not evidence that a previous low quota recovered.
    const rememberedLow = value === null ? state.low : low;
    return {
        state: {snapshot, error: null, busy: false, low: rememberedLow},
        notifyLow: low && !state.low,
    };
}

function applyFailure(state, error) {
    return Object.assign({}, state, {busy: false, error: String(error || '查询失败')});
}

if (typeof module !== 'undefined')
    module.exports = {validateSnapshot, summaryText, durationLabel, resetLabel, applySuccess, applyFailure, formatPercent, isLow};
