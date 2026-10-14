/* Калькулятор затирки. Без библиотек.
   Часть 1 — чистые функции расчёта (подключаются и в node для тестов);
   часть 2 — интерфейс, работает только в браузере.
   Формулы и константы совпадают с tools/calc_zatirka_ref.py — при правке менять оба файла. */
(function (root) {
    'use strict';

    // Затирки: плотность, кг/дм3; фасовки, кг. CE 33 Plus — ТДС Henkel; остальные — восстановлены из таблиц расхода производителей
    var GROUTS = {
        ce33: { name: 'Ceresit CE 33 Plus — цементная', short: 'Ceresit CE 33 Plus', rho: 1.1, packs: [2, 5] },
        ce40: { name: 'Ceresit CE 40 — цементная', short: 'Ceresit CE 40', rho: 1.1, packs: [2, 5] },
        mapei: { name: 'Mapei Keracolor FF — цементная', short: 'Mapei Keracolor FF', rho: 1.5, packs: [2, 5] },
        lle: { name: 'Litokol Litochrom Luxury EVO — цементная', short: 'Litokol Litochrom Luxury EVO', rho: 1.9, packs: [2] },
        epoxy: { name: 'Litokol Starlike EVO — эпоксидная', short: 'Litokol Starlike EVO', rho: 1.55, packs: [1, 2.5, 5] },
        custom: { name: 'Другая (указать плотность)', short: 'другая затирка', rho: null, packs: [2, 5] }
    };
    var RESERVE_DEFAULT = 10;
    var MAX_KG = 5000;

    function ceilEps(x) { return Math.ceil(Math.round(x * 1e9) / 1e9); }

    // "1,5" и "1.5" -> 1.5; пусто или мусор -> NaN
    function toNum(s) {
        if (typeof s === 'number') { return s; }
        var t = String(s == null ? '' : s).replace(/\s/g, '').replace(',', '.');
        if (t === '' || !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) { return NaN; }
        return parseFloat(t);
    }

    // кг/м2 без запаса: (A+B)/(A*B) * J * T * rho; размеры в мм
    function groutPerM2(aMm, bMm, jMm, tMm, rho) {
        return (aMm + bMm) / (aMm * bMm) * jMm * tMm * rho;
    }

    /* Наименее избыточная комбинация фасовок: минимум общего веса не меньше kg; при равенстве — меньше упаковок,
       затем больше крупных. Возвращает {parts:[{size,count}] от крупных к мелким, total}. */
    function bestCombo(kg, packs) {
        var ps = packs.slice().sort(function (x, y) { return y - x; });
        var best = null;
        function better(counts, total) {
            if (!best) { return true; }
            if (total < best.total - 1e-9) { return true; }
            if (total > best.total + 1e-9) { return false; }
            var s1 = counts.reduce(function (s, c) { return s + c; }, 0);
            var s2 = best.counts.reduce(function (s, c) { return s + c; }, 0);
            if (s1 !== s2) { return s1 < s2; }
            for (var i = 0; i < counts.length; i++) {
                if (counts[i] !== best.counts[i]) { return counts[i] > best.counts[i]; }
            }
            return false;
        }
        function rec(i, rest, chosen) {
            if (i === ps.length - 1) {
                var counts = chosen.concat([Math.max(0, ceilEps(rest / ps[i]))]);
                var total = counts.reduce(function (s, c, k) { return s + c * ps[k]; }, 0);
                if (better(counts, total)) { best = { counts: counts, total: total }; }
                return;
            }
            var top = Math.max(0, ceilEps(rest / ps[i]));
            for (var n = 0; n <= top; n++) { rec(i + 1, rest - n * ps[i], chosen.concat([n])); }
        }
        rec(0, kg, []);
        var parts = [];
        best.counts.forEach(function (c, k) { if (c > 0) { parts.push({ size: ps[k], count: c }); } });
        return { parts: parts, total: best.total };
    }

    /* Полный расчёт. inp: area (м2), a, b (см), thick, joint (мм), reserve (%), groutKey, rho (для custom).
       Значения — строки или числа. Возвращает {ok, errors:{поле: текст}, ...результаты}. */
    function calc(inp) {
        var err = {};
        function need(key, label, min, max, unit) {
            var v = toNum(inp[key]);
            if (isNaN(v)) { err[key] = 'Укажите ' + label + ' числом.'; return NaN; }
            if (v <= 0) { err[key] = 'Значение должно быть больше нуля.'; return NaN; }
            if (v < min || v > max) { err[key] = ('Допустимо от ' + min + ' до ' + max + ' ' + unit + '.').replace(/(\d)\.(\d)/g, '$1,$2'); return NaN; }
            return v;
        }
        var area = need('area', 'площадь', 0.1, 1000, 'м²');
        var a = need('a', 'сторону плитки', 1, 300, 'см');
        var b = need('b', 'сторону плитки', 1, 300, 'см');
        var thick = need('thick', 'толщину плитки', 2, 30, 'мм');
        var joint = need('joint', 'ширину шва', 1, 15, 'мм');
        var reserve = toNum(inp.reserve);
        if (isNaN(reserve) || reserve < 0 || reserve > 100) { err.reserve = 'Запас — число от 0 до 100 %.'; }
        if (!err.a && !err.b && !err.joint && joint >= Math.min(a, b) * 10) {
            err.joint = 'Шов не может быть больше или равен размеру плитки.';
        }
        var groutKey = GROUTS[inp.groutKey] ? inp.groutKey : 'ce33';
        var rho = GROUTS[groutKey].rho;
        if (groutKey === 'custom') { rho = need('rho', 'плотность', 0.5, 3, 'кг/дм³'); }
        if (Object.keys(err).length) { return { ok: false, errors: err }; }

        var perM2 = groutPerM2(a * 10, b * 10, joint, thick, rho);
        var factor = 1 + reserve / 100;
        var kgNet = area * perM2;
        var kg = kgNet * factor;
        if (kg > MAX_KG) {
            return { ok: false, errors: { sum: 'Получилось больше ' + MAX_KG + ' кг — проверьте площадь, размер плитки, шов и толщину.' } };
        }
        var packs = GROUTS[groutKey].packs.map(function (p) { return { size: p, count: ceilEps(kg / p) }; });
        var combo = GROUTS[groutKey].packs.length > 1 ? bestCombo(kg, GROUTS[groutKey].packs) : null;
        return {
            ok: true, errors: {}, area: area, a: a, b: b, thick: thick, joint: joint, reserve: reserve,
            groutKey: groutKey, rho: rho, perM2: perM2, kgNet: kgNet, kg: kg, factor: factor,
            packs: packs, combo: combo
        };
    }

    /* Для блока товаров: кг затирки с плотностью rho при тех же размерах и запасе. */
    function shopKg(r, rho) {
        return r.area * (r.perM2 / r.rho) * rho * r.factor;
    }

    var api = {
        calc: calc, toNum: toNum, groutPerM2: groutPerM2, bestCombo: bestCombo, shopKg: shopKg, ceilEps: ceilEps,
        GROUTS: GROUTS, RESERVE_DEFAULT: RESERVE_DEFAULT
    };
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
    root.CalcZatirka = api;

    if (typeof document === 'undefined') { return; }

    /* ---------------- интерфейс ---------------- */
    var form = document.getElementById('calc-form');
    if (!form) { return; }
    var $ = function (id) { return document.getElementById(id); };
    var wrap = $('calc-wrap');
    // пресет плитки: [a, b, толщина по умолчанию, мм]
    var PRESETS = {
        '2x2': [2, 2, 6], '5x5': [5, 5, 6], '10x10': [10, 10, 7], '20x30': [20, 30, 8], '25x40': [25, 40, 8],
        '30x30': [30, 30, 8], '30x60': [30, 60, 9], '60x60': [60, 60, 10], '60x120': [60, 120, 10]
    };
    var lastCount = 0, lastText = '';

    function fmt(x, d) {
        var s = x.toFixed(d == null ? 2 : d);
        if (s.indexOf('.') >= 0) { s = s.replace(/0+$/, '').replace(/\.$/, ''); }
        return s.replace('.', ',');
    }
    function esc(s) {
        return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
    }

    function read() {
        return {
            area: $('c-area').value, a: $('c-a').value, b: $('c-b').value, thick: $('c-thick').value,
            joint: $('c-joint').value, groutKey: $('c-grout').value, rho: $('c-rho').value, reserve: $('c-reserve').value
        };
    }

    /* --- состояние в URL (те же ключи принимает калькулятор плитки: a, b, t, j, g, rho) --- */
    var KEYS = { area: 's', a: 'a', b: 'b', thick: 't', joint: 'j', groutKey: 'g', rho: 'rho', reserve: 'r' };
    function saveUrl(inp) {
        var q = [];
        Object.keys(KEYS).forEach(function (k) {
            var v = String(inp[k]).replace(/\s/g, '');
            if (v !== '') { q.push(KEYS[k] + '=' + encodeURIComponent(v)); }
        });
        try { history.replaceState(null, '', '?' + q.join('&')); } catch (e) { /* file:// и т. п. */ }
    }
    function loadUrl() {
        var p = {};
        (location.search || '').replace(/^\?/, '').split('&').forEach(function (kv) {
            var i = kv.indexOf('=');
            if (i > 0) { try { p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* битая ссылка */ } }
        });
        if (!Object.keys(p).length) { return false; }
        [['s', 'c-area'], ['a', 'c-a'], ['b', 'c-b'], ['t', 'c-thick'], ['j', 'c-joint'], ['rho', 'c-rho'], ['r', 'c-reserve']].forEach(function (pr) {
            if (p[pr[0]] != null) { $(pr[1]).value = p[pr[0]]; }
        });
        if (p.g != null && GROUTS[p.g]) { $('c-grout').value = p.g; }
        syncPreset();
        return true;
    }

    function syncPreset() {
        var key = toNum($('c-a').value) + 'x' + toNum($('c-b').value);
        $('c-preset').value = PRESETS[key] ? key : 'custom';
    }
    function syncVisibility() {
        $('c-a-row').hidden = $('c-preset').value !== 'custom';
        $('c-b-row').hidden = $('c-preset').value !== 'custom';
        $('c-rho-row').hidden = $('c-grout').value !== 'custom';
    }
    // ссылка на калькулятор плитки: те же размер плитки, толщина, шов и затирка
    function syncLinks(inp) {
        var link = $('c-to-plitka');
        if (!link) { return; }
        var q = [];
        [['a', 'a'], ['b', 'b'], ['thick', 't'], ['joint', 'j'], ['groutKey', 'g'], ['rho', 'rho']].forEach(function (pr) {
            var v = String(inp[pr[0]]).replace(/\s/g, '');
            if (pr[0] === 'rho' && inp.groutKey !== 'custom') { return; }
            // в калькуляторе плитки нет Litochrom Luxury EVO: передаём как «другую» с его плотностью
            if (pr[0] === 'groutKey' && v === 'lle') { q.push('rho=' + encodeURIComponent(fmt(GROUTS.lle.rho, 2))); v = 'custom'; }
            if (v !== '') { q.push(pr[1] + '=' + encodeURIComponent(v)); }
        });
        // дверь по умолчанию, как в калькуляторе плитки
        q.push('o=' + encodeURIComponent('door:0,7x2'));
        link.setAttribute('href', '/kalkulyator-plitki/?' + q.join('&'));
    }

    /* --- вывод --- */
    var FIELD_IDS = { area: 'area', a: 'a', b: 'b', thick: 'thick', joint: 'joint', reserve: 'reserve', rho: 'rho' };
    var FIELD_NAMES = { area: 'площадь', a: 'сторона A', b: 'сторона B', thick: 'толщина плитки', joint: 'шов', reserve: 'запас', rho: 'плотность затирки' };
    var ERR_ORDER = ['area', 'a', 'b', 'thick', 'joint', 'reserve', 'rho'];
    function setErrors(errors) {
        Object.keys(FIELD_IDS).forEach(function (k) {
            var input = $('c-' + FIELD_IDS[k]), box = $('e-' + FIELD_IDS[k]);
            var msg = errors[k] || '';
            if (k === 'b' && errors.a) { msg = ''; } // a и b делят одно сообщение
            box.textContent = msg;
            if (errors[k]) { input.setAttribute('aria-invalid', 'true'); } else { input.removeAttribute('aria-invalid'); }
        });
        $('e-sum').textContent = errors.sum || '';
    }
    function showErrorBar(errors) {
        var bar = $('c-bar'), id = null, name = '';
        ERR_ORDER.some(function (k) {
            if (errors[k]) { id = 'c-' + FIELD_IDS[k]; name = FIELD_NAMES[k]; return true; }
            return false;
        });
        if (!id && errors.sum) { id = 'c-area'; name = 'размеры'; }
        if (!id) { bar.hidden = true; return; }
        $('c-bar-text').innerHTML = 'Исправьте поле: <a href="#' + id + '" data-focus="' + id + '">' + esc(name) + '</a>';
        $('c-bar-more').hidden = true;
        bar.hidden = false;
    }
    function packWord(n) {
        var m10 = n % 10, m100 = n % 100;
        return m10 === 1 && m100 !== 11 ? 'упаковка' : ([2, 3, 4].indexOf(m10) >= 0 && [12, 13, 14].indexOf(m100) < 0 ? 'упаковки' : 'упаковок');
    }
    function packsText(packs) {
        return packs.map(function (p) { return p.count + ' уп. по ' + fmt(p.size, 1) + ' кг'; }).join(' или ');
    }
    function comboText(c) {
        return c.parts.map(function (p) { return p.count + ' × ' + fmt(p.size, 1) + ' кг'; }).join(' + ');
    }
    function renderShop(r) {
        var c = $('c-shop-cem-calc'), e = $('c-shop-epoxy-calc');
        if (!c || !e) { return; }
        var kgC = r.ok ? shopKg(r, GROUTS.lle.rho) : NaN;
        var kgE = r.ok ? shopKg(r, GROUTS.epoxy.rho) : NaN;
        if (!isFinite(kgC) || !isFinite(kgE) || kgC <= 0) { c.hidden = true; e.hidden = true; return; }
        var nC = ceilEps(kgC / 2);
        c.textContent = 'По вашему расчёту: ' + nC + ' ' + packWord(nC) + ' по 2 кг (нужно ≈ ' + fmt(kgC, 1) + ' кг при плотности 1,9).';
        e.textContent = 'По вашему расчёту: ' + comboText(bestCombo(kgE, [2.5, 1])) + ' (нужно ≈ ' + fmt(kgE, 1) + ' кг при плотности 1,55).';
        c.hidden = false; e.hidden = false;
    }

    function render(r, inp) {
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
        var g = GROUTS[r.groutKey];
        var sub = packsText(r.packs);
        if (r.combo && r.combo.parts.length > 1) { sub += '. Меньше всего излишка: ' + comboText(r.combo) + ' (' + fmt(r.combo.total, 1) + ' кг)'; }
        var html = '<dl class="calc-out">' +
            '<div><dt>Расход ' + esc(g.short) + '</dt><dd><strong>' + fmt(r.perM2, 3) + ' кг/м²</strong><span class="calc-sub">без запаса</span></dd></div>' +
            '<div class="calc-main"><dt>Затирки нужно (запас ' + fmt(r.reserve, 1) + ' %)</dt><dd><strong>' + fmt(r.kg) + ' кг</strong><span class="calc-sub">' + esc(sub) + '</span></dd></div>' +
            '</dl>';
        if (r.groutKey === 'epoxy' || r.groutKey === 'lle' || r.groutKey === 'mapei') {
            html += '<p class="calc-note">Плотность ' + fmt(r.rho, 2) + ' кг/дм³ восстановлена из таблицы расхода производителя.</p>';
        }
        res.innerHTML = html;
        $('c-how').innerHTML = howText(r);
        bar.hidden = false;
        $('c-bar-text').textContent = 'Затирка ' + fmt(r.kg, 1) + ' кг · ' + fmt(r.perM2, 3) + ' кг/м²';
        $('c-bar-more').hidden = false;
        lastText = copyText(r);
        $('c-copy').disabled = false;
    }
    function howText(r) {
        var h = '<ol class="calc-how"><li><strong>Расход на 1 м².</strong> (A+B)/(A·B) × J × T × ρ = (' + fmt(r.a * 10) + '+' + fmt(r.b * 10) + ')/(' +
            fmt(r.a * 10) + '×' + fmt(r.b * 10) + ') × ' + fmt(r.joint) + ' × ' + fmt(r.thick) + ' × ' + fmt(r.rho, 2) + ' = ' + fmt(r.perM2, 3) +
            ' кг/м² (A, B — плитка в мм; J — шов, мм; T — толщина плитки, мм; ρ — плотность затирки, кг/дм³).</li>';
        h += '<li><strong>На всю площадь.</strong> ' + fmt(r.area) + ' м² × ' + fmt(r.perM2, 3) + ' = ' + fmt(r.kgNet) + ' кг.</li>';
        h += '<li><strong>Запас.</strong> × (1 + ' + fmt(r.reserve, 1) + '/100) = ' + fmt(r.kg) + ' кг.</li>';
        h += '<li><strong>Упаковки.</strong> ' + esc(packsText(r.packs)) + ' (округляем вверх).' +
            (r.combo && r.combo.parts.length > 1 ? ' Комбинация с минимальным излишком: ' + esc(comboText(r.combo)) + ' = ' + fmt(r.combo.total, 1) + ' кг.' : '') + '</li>';
        return h + '</ol><p class="calc-note">Это оценка: реальный расход зависит от ровности кромок плитки, глубины шва и от того, как затирают.</p>';
    }
    function copyText(r) {
        return ['Расчёт затирки, santehrazbor.ru',
            'Площадь: ' + fmt(r.area) + ' м², плитка ' + fmt(r.a) + '×' + fmt(r.b) + ' см, толщина ' + fmt(r.thick) + ' мм, шов ' + fmt(r.joint) + ' мм',
            'Затирка ' + GROUTS[r.groutKey].short + ' (ρ ' + fmt(r.rho, 2) + '): ' + fmt(r.perM2, 3) + ' кг/м²',
            'Нужно: ' + fmt(r.kg) + ' кг с запасом ' + fmt(r.reserve, 1) + ' % (' + packsText(r.packs) + ')',
            location.href].join('\n');
    }

    /* --- GoatCounter: не чаще раза в 10 с, только после изменений пользователя --- */
    function countEvent() {
        var now = Date.now();
        if (now - lastCount < 10000) { return; }
        lastCount = now;
        if (window.goatcounter && window.goatcounter.count) {
            window.goatcounter.count({ path: 'calc-zatirka', event: true });
        }
    }

    function update(fromUser) {
        syncVisibility();
        var inp = read();
        var r = calc(inp);
        render(r, inp);
        saveUrl(inp);
        syncLinks(inp);
        if (fromUser && r.ok) { countEvent(); }
    }

    /* --- события --- */
    $('c-preset').addEventListener('change', function () {
        var p = PRESETS[this.value];
        if (p) { $('c-a').value = p[0]; $('c-b').value = p[1]; $('c-thick').value = p[2]; }
    });
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
