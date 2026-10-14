/* Калькулятор объёма водонагревателя. Без библиотек.
   Часть 1 — чистые функции расчёта (подключаются и в node для тестов);
   часть 2 — интерфейс, работает только в браузере.
   Формулы и константы совпадают с tools/calc_vodonagrevatel_ref.py — при правке менять оба файла. */
(function (root) {
    'use strict';

    // Типовой ряд объёмов бытовых накопителей, л
    var STANDARD = [30, 50, 80, 100, 120, 150, 200];
    var SINK_FLOW = 7.2;        // л/мин, мойка со смесителем 0,12 л/с (СП 30.13330.2020, табл. А.1)
    var DAILY_PER_PERSON = 70;  // л горячей воды на жителя в сутки (СП 30.13330.2020, табл. А.2)
    var WATER_CAPACITY = 1.163; // Вт·ч/(л·К)
    var VOLTAGE = 230;          // В
    var BATH_FLOW = 15;         // л/мин, ванна со смесителем 0,25 л/с (СП 30.13330.2020, табл. А.1)
    var SMALL_LIMIT = 15;       // л: ниже — хватит малого бака или проточного под мойку
    var POWERS = [1.5, 2, 2.5, 3];
    var EPS = 1e-9;

    // "7,2" и "7.2" -> 7.2; пусто или мусор -> NaN
    function toNum(s) {
        if (typeof s === 'number') { return s; }
        var t = String(s == null ? '' : s).replace(/\s/g, '').replace(',', '.');
        if (t === '' || !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) { return NaN; }
        return parseFloat(t);
    }

    // округление «от половины вверх» (как half_up в эталоне)
    function halfUp(x) { return Math.floor(x + 0.5 + EPS); }

    function recommend(needL) {
        for (var i = 0; i < STANDARD.length; i++) {
            if (needL <= STANDARD[i] + EPS) { return STANDARD[i]; }
        }
        return null;
    }
    function heatMinutes(volumeL, tHot, tCold, powerKw) {
        return halfUp(WATER_CAPACITY * volumeL * (tHot - tCold) / (powerKw * 1000) * 60);
    }
    // группа товаров: до 100 л — свой объём, выше (и при > 200 л) — 100 л
    function shopGroup(rec) { return (rec === null || rec > 100) ? 100 : rec; }

    // сколько литров воды ТЭН нагревает за час с tCold до tHot
    function perHour(powerKw, tHot, tCold) { return powerKw * 1000 / (WATER_CAPACITY * (tHot - tCold)); }

    function calc(inp) {
        var err = {};
        function range(key, label, min, max, unit, integer) {
            var v = toNum(inp[key]);
            if (isNaN(v)) { err[key] = 'Укажите ' + label + ' числом.'; return NaN; }
            if (v < min || v > max) { err[key] = ('Допустимо от ' + min + ' до ' + max + ' ' + unit + '.').replace(/(\d)\.(\d)/g, '$1,$2'); return NaN; }
            if (integer && v !== Math.floor(v)) { err[key] = 'Нужно целое число.'; return NaN; }
            return v;
        }
        var people = range('people', 'число людей', 1, 10, 'человек', true);
        var minutes = range('minutes', 'минуты на душ', 1, 60, 'мин');
        var flow = range('flow', 'расход душа', 1, 30, 'л/мин');
        var bath = !!inp.bath;
        var bathL = 0;
        if (bath) { bathL = range('bathL', 'объём набора ванны', 10, 500, 'л'); }
        var pause = range('pause', 'перерыв между душами', 0, 60, 'мин');
        var reheat = inp.reheat !== false;
        var dish = range('dish', 'минуты мытья посуды', 0, 120, 'мин');
        var tMix = range('tMix', 'температуру смешанной воды', 35, 45, '°C');
        var tHot = range('tHot', 'температуру нагрева бака', 50, 75, '°C');
        var tCold = range('tCold', 'температуру холодной воды', 1, 25, '°C');
        var power = toNum(inp.power);
        if (POWERS.indexOf(power) < 0) { power = 2; }
        if (!err.tHot && !err.tMix && tHot <= tMix) { err.tHot = 'Вода в баке должна быть горячее смешанной воды.'; }
        if (!err.tCold && !err.tMix && tCold >= tMix) { err.tCold = 'Холодная вода должна быть холоднее смешанной.'; }
        if (Object.keys(err).length) { return { ok: false, errors: err }; }

        var mix = people * minutes * flow + (bath ? bathL : 0) + dish * SINK_FLOW;
        var hot = mix * (tMix - tCold) / (tHot - tCold);
        var peak = people * minutes + (people - 1) * pause + dish + (bath ? bathL / BATH_FLOW : 0);
        var dog = reheat ? power * 1000 * peak / 60 / (WATER_CAPACITY * (tHot - tCold)) : 0;
        var need = Math.max(hot - dog, 0);
        var rec = recommend(need);
        return {
            ok: true, people: people, minutes: minutes, flow: flow, bath: bath, bathL: bathL, dish: dish,
            tMix: tMix, tHot: tHot, tCold: tCold, power: power, pause: pause, reheatOn: reheat,
            mix: mix, hot: hot, peakMin: peak, reheat: dog, perHour: perHour(power, tHot, tCold), need: need, rec: rec,
            small: need <= SMALL_LIMIT + EPS,
            heatMin: rec === null ? null : heatMinutes(rec, tHot, tCold, power),
            daily: DAILY_PER_PERSON * people,
            amps: power * 1000 / VOLTAGE,
            group: shopGroup(rec)
        };
    }

    var api = { calc: calc, toNum: toNum, recommend: recommend, heatMinutes: heatMinutes, halfUp: halfUp, shopGroup: shopGroup, STANDARD: STANDARD };
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
    root.CalcVodonagrevatel = api;

    if (typeof document === 'undefined') { return; }

    /* ---------------- интерфейс ---------------- */
    var form = document.getElementById('calc-form');
    if (!form) { return; }
    var $ = function (id) { return document.getElementById(id); };
    var wrap = $('calc-wrap');
    var FIELDS = ['people', 'minutes', 'flow', 'pause', 'bathL', 'dish', 'tMix', 'tHot', 'tCold', 'power'];
    var FIELD_NAMES = {
        people: 'число людей', pause: 'перерыв между душами', minutes: 'минуты на душ', flow: 'расход душа', bathL: 'объём ванны', dish: 'минуты посуды',
        tMix: 'температура смеси', tHot: 'температура в баке', tCold: 'холодная вода', power: 'мощность'
    };
    var lastCount = 0, lastText = '';

    function fmt(x, d) {
        var s = x.toFixed(d == null ? 0 : d);
        if (s.indexOf('.') >= 0) { s = s.replace(/0+$/, '').replace(/\.$/, ''); }
        return s.replace('.', ',');
    }
    function esc(s) {
        return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
    }
    function hm(min) {
        var h = Math.floor(min / 60), m = min % 60;
        return h ? h + ' ч ' + m + ' мин' : m + ' мин';
    }

    function read() {
        return {
            people: $('c-people').value, minutes: $('c-minutes').value, flow: $('c-flow').value,
            pause: $('c-pause').value, reheat: $('c-reheat').checked,
            bath: $('c-bath').checked, bathL: $('c-bathL').value, dish: $('c-dish').value,
            tMix: $('c-tMix').value, tHot: $('c-tHot').value, tCold: $('c-tCold').value, power: $('c-power').value
        };
    }

    /* --- состояние в URL (короткие ключи) --- */
    var KEYS = { people: 'p', minutes: 'm', flow: 'f', pause: 'pz', bathL: 'bl', dish: 'd', tMix: 'tm', tHot: 'th', tCold: 'tc', power: 'w' };
    function saveUrl(inp) {
        var q = [];
        Object.keys(KEYS).forEach(function (k) {
            if (k === 'bathL' && !inp.bath) { return; }
            var v = String(inp[k]).replace(/\s/g, '');
            if (v !== '') { q.push(KEYS[k] + '=' + encodeURIComponent(v)); }
        });
        q.push('b=' + (inp.bath ? '1' : '0'));
        q.push('rh=' + (inp.reheat ? '1' : '0'));
        try { history.replaceState(null, '', '?' + q.join('&')); } catch (e) { /* file:// и т. п. */ }
    }
    function loadUrl() {
        var p = {};
        (location.search || '').replace(/^\?/, '').split('&').forEach(function (kv) {
            var i = kv.indexOf('=');
            if (i > 0) { try { p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* битая ссылка */ } }
        });
        if (!Object.keys(p).length) { return false; }
        Object.keys(KEYS).forEach(function (k) {
            if (p[KEYS[k]] != null) { $('c-' + k).value = p[KEYS[k]]; }
        });
        if (p.b != null) { $('c-bath').checked = p.b === '1'; }
        if (p.rh != null) { $('c-reheat').checked = p.rh === '1'; }
        return true;
    }
    function syncVisibility() { $('c-bathL-row').hidden = !$('c-bath').checked; }

    function setErrors(errors) {
        FIELDS.forEach(function (k) {
            var input = $('c-' + k), box = $('e-' + k);
            box.textContent = errors[k] || '';
            if (errors[k]) { input.setAttribute('aria-invalid', 'true'); } else { input.removeAttribute('aria-invalid'); }
        });
    }
    function showErrorBar(errors) {
        var bar = $('c-bar'), key = null;
        FIELDS.some(function (k) { if (errors[k]) { key = k; return true; } return false; });
        if (!key) { bar.hidden = true; return; }
        $('c-bar-text').innerHTML = 'Исправьте поле: <a href="#c-' + key + '" data-focus="c-' + key + '">' + esc(FIELD_NAMES[key]) + '</a>';
        $('c-bar-more').hidden = true;
        bar.hidden = false;
    }

    function ampsAdvice(r) {
        var t = 'нужна исправная розетка с заземлением на 16 А';
        if (r.power >= 2.5) { t += '; при 2,5–3 кВт лучше отдельная линия'; }
        return t;
    }

    /* --- блок товаров: показываем группу рекомендуемого объёма --- */
    function renderShop(r) {
        var groups = document.querySelectorAll('.calc-shop-group');
        if (!groups.length) { return; }
        var g = r.ok ? r.group : null;
        var note = '';
        if (r.ok) {
            if (r.rec === null) {
                note = 'Расчёт дал ' + fmt(r.need) + ' л из бака — больше одного бытового бака. Ниже самый большой из подобранных, 100 л: смотрите его как базу для схемы из двух баков или обсудите вариант со специалистом.';
            } else if (r.rec > 100) {
                note = 'По расчёту нужен бак на ' + r.rec + ' л, а наибольший из подобранных — 100 л. Он закроет часть вечера: остальное придётся растянуть или взять бак на ' + r.rec + ' л другой модели.';
            } else if (r.small) {
                note = 'Расчёт дал всего ' + fmt(r.need, 1) + ' л горячей воды: для такого случая хватит и малого бака или проточного под мойку, но из подобранных самый маленький — 30 л.';
            }
        }
        var shown = false;
        groups.forEach(function (el) {
            var on = g !== null && Number(el.getAttribute('data-vol')) === g;
            el.hidden = g !== null && !on;
            var n = el.querySelector('.calc-shop-note');
            if (n) {
                n.textContent = on ? note : '';
                n.hidden = !(on && note);
            }
            if (on) { shown = true; }
        });
        if (g !== null && !shown) { groups.forEach(function (el) { el.hidden = false; }); }
    }

    function render(r) {
        var res = $('c-result'), bar = $('c-bar');
        renderShop(r);
        if (!r.ok) {
            setErrors(r.errors);
            res.innerHTML = '<p class="calc-wait">Исправьте отмеченные поля — результат появится сразу.</p>';
            $('c-how').innerHTML = '';
            showErrorBar(r.errors);
            lastText = '';
            $('c-copy').disabled = true;
            return;
        }
        setErrors({});
        var html = '<dl class="calc-out">';
        html += '<div><dt>Смешанной воды за вечер</dt><dd><strong>≈ ' + fmt(r.mix) + ' л</strong><span class="calc-sub">воды ' + fmt(r.tMix) + ' °C из крана</span></dd></div>';
        html += '<div><dt>Горячей воды в смеси</dt><dd><strong>≈ ' + fmt(r.hot) + ' л</strong><span class="calc-sub">воды ' + fmt(r.tHot) + ' °C: горячую разбавляют холодной</span></dd></div>';
        if (r.reheatOn) {
            html += '<div><dt>Догрев за время мытья</dt><dd><strong>≈ ' + fmt(r.reheat) + ' л</strong><span class="calc-sub">' + fmt(r.peakMin) + ' мин при ' + fmt(r.power, 1) + ' кВт</span></dd></div>';
        }
        html += '<div class="calc-main"><dt>Нужно из бака</dt><dd><strong>≈ ' + fmt(r.need) + ' л</strong><span class="calc-sub">' + (r.reheatOn ? 'горячая вода минус догрев во время мытья' : 'без учёта догрева во время мытья') + '</span></dd></div>';
        html += '<div><dt>За час ТЭН нагревает</dt><dd><strong>≈ ' + fmt(r.perHour) + ' л</strong><span class="calc-sub">с ' + fmt(r.tCold) + ' до ' + fmt(r.tHot) + ' °C при ' + fmt(r.power, 1) + ' кВт</span></dd></div>';
        if (r.rec === null) {
            html += '<div><dt>Рекомендуемый объём</dt><dd><strong>больше 200 л</strong><span class="calc-sub">больше, чем держит бытовой бак: разнесите ванну и души по времени (бак догревается ≈ ' + fmt(r.perHour) + ' л в час), поставьте два бака или рассмотрите газовую колонку</span></dd></div>';
        } else {
            html += '<div><dt>Рекомендуемый объём</dt><dd><strong>' + r.rec + ' л</strong><span class="calc-sub">ближайший стандартный вверх: смешивание в баке неидеально, запас на это не считаем</span></dd></div>';
            html += '<div><dt>Нагрев бака ' + r.rec + ' л с ' + fmt(r.tCold) + ' до ' + fmt(r.tHot) + ' °C при ' + fmt(r.power, 1) + ' кВт</dt><dd><strong>≈ ' + esc(hm(r.heatMin)) + '</strong><span class="calc-sub">без учёта теплопотерь — по паспорту обычно чуть дольше</span></dd></div>';
        }
        html += '<div><dt>Справочно: суточная норма</dt><dd><strong>≈ ' + fmt(r.daily) + ' л</strong><span class="calc-sub">70 л горячей воды на жителя в сутки, если в семье ' + r.people + ' чел. (СП 30.13330.2020, табл. А.2). Бак не обязан вмещать сутки — он догревается между пиками</span></dd></div>';
        html += '<div><dt>Ток ТЭНа (' + fmt(r.power, 1) + ' кВт)</dt><dd><strong>≈ ' + fmt(r.amps, 1) + ' А</strong><span class="calc-sub">' + esc(ampsAdvice(r)) + '</span></dd></div>';
        html += '</dl>';
        if (r.small) {
            html += '<p class="calc-note">Нужно меньше 15 л горячей воды: хватит малого бака или проточного нагревателя под мойку. Минимум из ряда накопителей — 30 л.</p>';
        }
        html += '<p class="calc-note">Это оценка: вода в баке остывает, смеситель и душ расходуют по-разному, а температура холодной воды зимой меняется.</p>';
        res.innerHTML = html;
        $('c-how').innerHTML = howText(r);
        bar.hidden = false;
        $('c-bar-text').textContent = r.rec === null
            ? 'Нужно ≈ ' + fmt(r.need) + ' л · больше 200 л'
            : 'Бак ' + r.rec + ' л · нужно ≈ ' + fmt(r.need) + ' л';
        $('c-bar-more').hidden = false;
        lastText = copyText(r);
        $('c-copy').disabled = false;
    }

    function howText(r) {
        var h = '<ol class="calc-how">';
        h += '<li><strong>Смешанная вода.</strong> ' + r.people + ' × ' + fmt(r.minutes, 1) + ' мин × ' + fmt(r.flow, 1) + ' л/мин' +
            (r.bath ? ' + ванна ' + fmt(r.bathL) + ' л' : '') + (r.dish > 0 ? ' + посуда ' + fmt(r.dish, 1) + ' мин × 7,2 л/мин' : '') +
            ' = ' + fmt(r.mix, 1) + ' л.</li>';
        h += '<li><strong>Горячая вода в смеси.</strong> V × (T<sub>смеси</sub> − T<sub>хол</sub>) / (T<sub>бака</sub> − T<sub>хол</sub>) = ' +
            fmt(r.mix, 1) + ' × (' + fmt(r.tMix) + ' − ' + fmt(r.tCold) + ') / (' + fmt(r.tHot) + ' − ' + fmt(r.tCold) + ') = ' + fmt(r.hot, 1) + ' л.</li>';
        if (r.reheatOn) {
            h += '<li><strong>Догрев за время мытья.</strong> Пик длится ' + fmt(r.peakMin, 1) + ' мин (люди × минуты + перерывы + посуда + ванна / 15 л/мин). ТЭН за это время нагревает P × T / (1,163 × ΔT) = ' +
                fmt(r.power * 1000) + ' × ' + fmt(r.peakMin, 1) + ' / 60 / (1,163 × ' + fmt(r.tHot - r.tCold) + ') = ' + fmt(r.reheat, 1) + ' л. Нужно из бака: ' + fmt(r.hot, 1) + ' − ' + fmt(r.reheat, 1) + ' = ' + fmt(r.need, 1) + ' л.</li>';
        } else {
            h += '<li><strong>Догрев не учитывается.</strong> Из бака нужно всё количество горячей воды: ' + fmt(r.need, 1) + ' л.</li>';
        }
        h += r.rec === null
            ? '<li><strong>Объём.</strong> Больше 200 л — за пределом ряда бытовых накопителей (30, 50, 80, 100, 120, 150, 200 л).</li>'
            : '<li><strong>Объём.</strong> Ближайший вверх из ряда 30, 50, 80, 100, 120, 150, 200 л: ' + r.rec + ' л.</li>';
        if (r.rec !== null) {
            h += '<li><strong>Время нагрева.</strong> 1,163 × V × (T<sub>бака</sub> − T<sub>хол</sub>) / P = 1,163 × ' + r.rec + ' × ' + fmt(r.tHot - r.tCold) +
                ' / ' + fmt(r.power * 1000) + ' Вт = ' + fmt(r.heatMin / 60, 2) + ' ч (1,163 Вт·ч/(л·К) — теплоёмкость воды).</li>';
        }
        h += '<li><strong>Ток.</strong> P / 230 В = ' + fmt(r.power * 1000) + ' / 230 = ' + fmt(r.amps, 1) + ' А.</li>';
        return h + '</ol>';
    }

    function copyText(r) {
        return ['Расчёт водонагревателя, santehrazbor.ru',
            r.people + ' чел. по ' + fmt(r.minutes, 1) + ' мин, душ ' + fmt(r.flow, 1) + ' л/мин' + (r.bath ? ', ванна ' + fmt(r.bathL) + ' л' : '') +
                (r.dish > 0 ? ', посуда ' + fmt(r.dish, 1) + ' мин' : '') + '; смесь ' + fmt(r.tMix) + ' °C, бак ' + fmt(r.tHot) + ' °C, холодная ' + fmt(r.tCold) + ' °C',
            'Горячей воды в смеси ≈ ' + fmt(r.hot) + ' л' + (r.reheatOn ? ', догрев за ' + fmt(r.peakMin) + ' мин ≈ ' + fmt(r.reheat) + ' л' : '') + '; нужно из бака ≈ ' + fmt(r.need) + ' л',
            r.rec === null ? 'Объём: больше 200 л, один бак не справится' : 'Рекомендуемый объём: ' + r.rec + ' л, нагрев ≈ ' + hm(r.heatMin) + ' при ' + fmt(r.power, 1) + ' кВт',
            location.href].join('\n');
    }

    /* --- GoatCounter: не чаще раза в 10 с, только после изменений пользователя --- */
    function countEvent() {
        var now = Date.now();
        if (now - lastCount < 10000) { return; }
        lastCount = now;
        if (window.goatcounter && window.goatcounter.count) {
            window.goatcounter.count({ path: 'calc-vodonagrevatel', event: true });
        }
    }

    function update(fromUser) {
        syncVisibility();
        var inp = read();
        var r = calc(inp);
        render(r);
        saveUrl(inp);
        if (fromUser && r.ok) { countEvent(); }
    }

    /* --- события --- */
    form.addEventListener('input', function () { update(true); });
    form.addEventListener('change', function () { update(true); });
    $('c-bar').addEventListener('click', function (e) {
        var id = e.target.getAttribute && e.target.getAttribute('data-focus');
        if (!id) { return; }
        e.preventDefault();
        var el = $(id);
        if (el) { el.scrollIntoView({ block: 'center' }); el.focus(); }
    });
    form.addEventListener('submit', function (e) { e.preventDefault(); });

    $('c-copy').addEventListener('click', function () {
        var st = $('c-copy-status');
        function done(ok) { st.textContent = ok ? 'Скопировано' : 'Не удалось скопировать — выделите текст результата вручную.'; }
        if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(lastText).then(function () { done(true); }, function () { done(false); });
        } else { done(false); }
    });

    // плашка с итогом внизу экрана — только пока блок результата не виден
    if ('IntersectionObserver' in window) {
        new IntersectionObserver(function (es) {
            $('c-bar').classList.toggle('is-off', es[0].isIntersecting);
        }, { threshold: 0.2 }).observe($('c-result-box'));
    }

    loadUrl();
    wrap.hidden = false;
    update(false);
})(typeof window !== 'undefined' ? window : globalThis);
