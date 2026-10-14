/* Калькулятор плитки, клея и затирки. Без библиотек.
   Часть 1 — чистые функции расчёта (подключаются и в node для тестов);
   часть 2 — интерфейс, работает только в браузере.
   Формулы и константы совпадают с tools/calc_plitka_ref.py — при правке менять оба файла. */
(function (root) {
    'use strict';

    // Запас плитки: «обычно берут», у производителей цифр нет
    var LAYOUT_RESERVE = { straight: 10, diagonal: 15, herringbone: 20 };
    // Затирки: плотность, кг/дм3. CE 33 Plus — ТДС Henkel; Mapei Keracolor FF и Litokol Starlike EVO — по таблицам производителей
    var GROUTS = {
        ce33: { name: 'Ceresit CE 33 Plus', rho: 1.1, packs: [2, 5] },
        ce40: { name: 'Ceresit CE 40', rho: 1.1, packs: [2, 5] },
        mapei: { name: 'Mapei Keracolor FF', rho: 1.5, packs: [2, 5] },
        epoxy: { name: 'Litokol Starlike EVO (эпоксидная)', rho: 1.55, packs: [1, 2.5, 5] },
        custom: { name: 'своя затирка', rho: null, packs: [2, 5] }
    };
    var GROUT_RESERVE = 1.1;
    // Клей Ceresit CM 11 Plus: предел большей стороны (см), зуб (мм), расход (кг/м2)
    var GLUE_TABLE = [[10, 4, 2.0], [15, 6, 2.7], [25, 8, 3.4], [30, 10, 4.2], [Infinity, 12, 4.8]];
    var GLUE_BAG_KG = 25;
    var TEETH = [4, 6, 8, 10, 12];

    function ceilEps(x) { return Math.ceil(Math.round(x * 1e9) / 1e9); }

    // "1,5" и "1.5" -> 1.5; пусто или мусор -> NaN
    function toNum(s) {
        if (typeof s === 'number') { return s; }
        var t = String(s == null ? '' : s).replace(/\s/g, '').replace(',', '.');
        if (t === '' || !/^[-+]?(\d+\.?\d*|\.\d+)$/.test(t)) { return NaN; }
        return parseFloat(t);
    }

    function toothFor(maxSideCm) {
        for (var i = 0; i < GLUE_TABLE.length; i++) {
            if (maxSideCm <= GLUE_TABLE[i][0]) { return GLUE_TABLE[i][1]; }
        }
    }
    function glueRate(tooth) {
        for (var i = 0; i < GLUE_TABLE.length; i++) {
            if (GLUE_TABLE[i][1] === tooth) { return GLUE_TABLE[i][2]; }
        }
    }
    // кг/м2 без запаса: (A+B)/(A*B) * J * T * rho; размеры в мм
    function groutPerM2(aMm, bMm, jMm, tMm, rho) {
        return (aMm + bMm) / (aMm * bMm) * jMm * tMm * rho;
    }

    /* Полный расчёт. inp: mode ('floor'|'walls'|'both'), len, wid, hgt (м), openings [{w,h}] (м),
       a, b (см), thick, joint (мм), boxKind ('none'|'m2'|'pcs'), boxVal, reserve (%),
       groutKey, rho (для custom), tooth (мм или 0/пусто = авто).
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
        var mode = inp.mode || 'both';
        var useFloor = mode === 'floor' || mode === 'both';
        var useWalls = mode === 'walls' || mode === 'both';
        var len = need('len', 'длину', 0.1, 100, 'м');
        var wid = need('wid', 'ширину', 0.1, 100, 'м');
        var hgt = useWalls ? need('hgt', 'высоту облицовки', 0.1, 10, 'м') : 0;
        var a = need('a', 'сторону плитки', 1, 300, 'см');
        var b = need('b', 'сторону плитки', 1, 300, 'см');
        var thick = need('thick', 'толщину плитки', 3, 30, 'мм');
        var joint = need('joint', 'ширину шва', 0.5, 20, 'мм');
        var reserve = toNum(inp.reserve);
        if (isNaN(reserve) || reserve < 0 || reserve > 100) { err.reserve = 'Запас — число от 0 до 100 %.'; }
        if (!err.a && !err.b && !err.joint && joint >= Math.min(a, b) * 10) {
            err.joint = 'Шов не может быть больше или равен размеру плитки.';
        }
        var boxKind = inp.boxKind || 'none';
        var boxVal = NaN;
        if (boxKind !== 'none') { boxVal = need('boxVal', 'число в коробке', 0.01, 1000, boxKind === 'm2' ? 'м²' : 'шт'); }
        var groutKey = GROUTS[inp.groutKey] ? inp.groutKey : 'ce33';
        var rho = GROUTS[groutKey].rho;
        if (groutKey === 'custom') { rho = need('rho', 'плотность', 0.5, 3, 'кг/дм³'); }

        // проёмы вычитаются из площади стен
        var openingsArea = 0;
        var openings = inp.openings || [];
        if (useWalls) {
            for (var i = 0; i < openings.length; i++) {
                var ow = toNum(openings[i].w), oh = toNum(openings[i].h);
                if (isNaN(ow) || isNaN(oh) || ow <= 0 || oh <= 0 || ow > 20 || oh > 10) {
                    err['open' + i] = 'Ширина и высота проёма — числа больше нуля (до 20 и 10 м).';
                } else { openingsArea += ow * oh; }
            }
        }
        var floorArea = 0, wallArea = 0, perimeter = 0;
        if (!err.len && !err.wid) {
            if (useFloor) { floorArea = len * wid; }
            perimeter = 2 * (len + wid);
        }
        if (useWalls && !err.len && !err.wid && !err.hgt) {
            wallArea = perimeter * hgt;
            var openBad = Object.keys(err).some(function (k) { return k.indexOf('open') === 0; });
            if (!openBad && openingsArea >= wallArea) {
                err.openings = 'Проёмы (' + openingsArea.toFixed(2).replace('.', ',') + ' м²) не меньше площади стен (' +
                    wallArea.toFixed(2).replace('.', ',') + ' м²) — проверьте размеры.';
            }
        }
        if (Object.keys(err).length) { return { ok: false, errors: err }; }

        var area = floorArea + wallArea - openingsArea;
        var tileM2 = a / 100 * b / 100;
        var pcs = ceilEps(area * (1 + reserve / 100) / tileM2);
        var boxes = null;
        if (boxKind === 'pcs') { boxes = ceilEps(pcs / boxVal); }
        else if (boxKind === 'm2') { boxes = ceilEps(pcs * tileM2 / boxVal); }

        var perM2 = groutPerM2(a * 10, b * 10, joint, thick, rho);
        var groutKg = area * perM2 * GROUT_RESERVE;
        var packs = GROUTS[groutKey].packs.map(function (p) { return { size: p, count: ceilEps(groutKg / p) }; });

        var maxSide = Math.max(a, b);
        var autoTooth = toothFor(maxSide);
        var tooth = TEETH.indexOf(toNum(inp.tooth)) >= 0 ? toNum(inp.tooth) : autoTooth;
        var rate = glueRate(tooth);
        var glueKg = area * rate;

        return {
            ok: true, errors: {}, mode: mode, perimeter: perimeter,
            floorArea: floorArea, wallArea: wallArea, openingsArea: openingsArea, area: area,
            tileM2: tileM2, reserve: reserve, pcsNoReserve: ceilEps(area / tileM2), pcs: pcs, boxes: boxes,
            boxKind: boxKind, boxVal: boxVal,
            groutKey: groutKey, rho: rho, groutPerM2: perM2, groutKg: groutKg, groutPacks: packs,
            tooth: tooth, autoTooth: autoTooth, glueRate: rate, glueKg: glueKg,
            glueBags: ceilEps(glueKg / GLUE_BAG_KG), bothSidesHint: maxSide > 30
        };
    }

    var api = {
        calc: calc, toNum: toNum, toothFor: toothFor, glueRate: glueRate, groutPerM2: groutPerM2,
        GROUTS: GROUTS, LAYOUT_RESERVE: LAYOUT_RESERVE, GLUE_TABLE: GLUE_TABLE, GLUE_BAG_KG: GLUE_BAG_KG,
        GROUT_RESERVE: GROUT_RESERVE
    };
    if (typeof module !== 'undefined' && module.exports) { module.exports = api; }
    root.CalcPlitka = api;

    if (typeof document === 'undefined') { return; }

    /* ---------------- интерфейс ---------------- */
    var form = document.getElementById('calc-form');
    if (!form) { return; }
    var $ = function (id) { return document.getElementById(id); };
    var wrap = $('calc-wrap');
    // пресет плитки: [a, b, толщина по умолчанию, мм]
    var PRESETS = { '20x30': [20, 30, 8], '25x40': [25, 40, 8], '30x60': [30, 60, 9], '60x60': [60, 60, 10], '60x120': [60, 120, 10] };
    // типовые размеры проёмов: название, ширина, высота (м) — можно править в строке
    var OPEN_KINDS = { door: ['Дверь', 0.8, 2.0], window: ['Окно', 1.2, 1.2], bath: ['Ванна или экран', 1.7, 0.6] };
    var thickTouched = false;
    var lastCount = 0, openSeq = 0, lastText = '';

    function fmt(x, d) {
        var s = x.toFixed(d == null ? 2 : d);
        if (s.indexOf('.') >= 0) { s = s.replace(/0+$/, '').replace(/\.$/, ''); }
        return s.replace('.', ',');
    }
    function esc(s) {
        return String(s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
    }
    function radio(name) {
        var el = form.querySelector('input[name="' + name + '"]:checked');
        return el ? el.value : '';
    }
    function setRadio(name, v) {
        var el = form.querySelector('input[name="' + name + '"][value="' + v + '"]');
        if (el) { el.checked = true; }
    }

    /* --- проёмы --- */
    var openList = $('c-openings');
    function addOpening(kind, w, h) {
        var k = OPEN_KINDS[kind] || OPEN_KINDS.door;
        var id = 'o' + (openSeq++);
        var row = document.createElement('div');
        row.className = 'calc-open';
        row.setAttribute('data-kind', kind);
        row.innerHTML =
            '<span class="calc-open-name">' + k[0] + '</span>' +
            '<label for="' + id + 'w">Ширина, м</label><input id="' + id + 'w" type="text" inputmode="decimal" autocomplete="off" value="' + esc(typeof w === 'string' ? w : fmt(w == null ? k[1] : w)) + '">' +
            '<label for="' + id + 'h">Высота, м</label><input id="' + id + 'h" type="text" inputmode="decimal" autocomplete="off" value="' + esc(typeof h === 'string' ? h : fmt(h == null ? k[2] : h)) + '">' +
            '<button type="button" class="calc-remove" aria-label="Удалить проём: ' + k[0] + '">Удалить</button>' +
            '<span class="calc-err" role="alert"></span>';
        openList.appendChild(row);
    }
    function readOpenings() {
        return Array.prototype.map.call(openList.children, function (row) {
            var ins = row.querySelectorAll('input');
            return { kind: row.getAttribute('data-kind'), w: ins[0].value, h: ins[1].value };
        });
    }
    ['door', 'window', 'bath'].forEach(function (kind) {
        $('c-add-' + kind).addEventListener('click', function () { addOpening(kind); update(true); });
    });
    openList.addEventListener('click', function (e) {
        if (e.target.classList.contains('calc-remove')) {
            openList.removeChild(e.target.parentNode);
            update(true);
        }
    });

    /* --- чтение формы --- */
    function read() {
        return {
            mode: radio('mode'), len: $('c-len').value, wid: $('c-wid').value, hgt: $('c-hgt').value,
            openings: readOpenings(), a: $('c-a').value, b: $('c-b').value,
            thick: $('c-thick').value, joint: $('c-joint').value,
            boxKind: $('c-boxkind').value, boxVal: $('c-boxval').value,
            layout: radio('layout'), reserve: $('c-reserve').value,
            groutKey: $('c-grout').value, rho: $('c-rho').value, tooth: $('c-tooth').value
        };
    }

    /* --- состояние в URL --- */
    var KEYS = { mode: 'm', len: 'l', wid: 'w', hgt: 'h', a: 'a', b: 'b', thick: 't', joint: 'j', boxKind: 'bk', boxVal: 'bv', layout: 'ly', reserve: 'r', groutKey: 'g', rho: 'rho', tooth: 'z' };
    function saveUrl(inp) {
        var q = [];
        Object.keys(KEYS).forEach(function (k) {
            var v = String(inp[k]).replace(/\s/g, '');
            if (v !== '') { q.push(KEYS[k] + '=' + encodeURIComponent(v)); }
        });
        q.push('o=' + encodeURIComponent(inp.openings.map(function (o) {
            return o.kind + ':' + String(o.w).replace(/\s/g, '') + 'x' + String(o.h).replace(/\s/g, '');
        }).join(',') || '-'));
        try { history.replaceState(null, '', '?' + q.join('&')); } catch (e) { /* file:// и т. п. */ }
    }
    function loadUrl() {
        var p = {};
        (location.search || '').replace(/^\?/, '').split('&').forEach(function (kv) {
            var i = kv.indexOf('=');
            if (i > 0) { try { p[kv.slice(0, i)] = decodeURIComponent(kv.slice(i + 1)); } catch (e) { /* битая ссылка */ } }
        });
        if (!Object.keys(p).length) { return false; }
        if (p.m) { setRadio('mode', p.m); }
        if (p.ly) { setRadio('layout', p.ly); }
        [['l', 'c-len'], ['w', 'c-wid'], ['h', 'c-hgt'], ['a', 'c-a'], ['b', 'c-b'], ['t', 'c-thick'], ['j', 'c-joint'],
         ['bk', 'c-boxkind'], ['bv', 'c-boxval'], ['r', 'c-reserve'], ['g', 'c-grout'], ['rho', 'c-rho'], ['z', 'c-tooth']].forEach(function (pr) {
            if (p[pr[0]] != null) { $(pr[1]).value = p[pr[0]]; }
        });
        if (p.o != null) {
            openList.innerHTML = '';
            if (p.o !== '-') {
                p.o.split(',').slice(0, 12).forEach(function (s) {
                    var m = /^(door|window|bath):([^x]+)x(.+)$/.exec(s);
                    if (m) { addOpening(m[1], m[2], m[3]); }
                });
            }
        }
        thickTouched = true;
        syncPreset();
        return true;
    }

    /* --- зависимости полей --- */
    function syncPreset() {
        var key = toNum($('c-a').value) + 'x' + toNum($('c-b').value);
        $('c-preset').value = PRESETS[key] ? key : 'custom';
    }
    function syncVisibility() {
        var mode = radio('mode');
        $('c-hgt-row').hidden = mode === 'floor';
        $('c-open-block').hidden = mode === 'floor';
        $('c-boxval-row').hidden = $('c-boxkind').value === 'none';
        $('c-boxval-label').textContent = $('c-boxkind').value === 'pcs' ? 'Штук в коробке' : 'Площадь плитки в коробке, м²';
        $('c-rho-row').hidden = $('c-grout').value !== 'custom';
    }

    /* --- вывод --- */
    function setErrors(errors) {
        var map = { len: 'len', wid: 'wid', hgt: 'hgt', a: 'a', b: 'b', thick: 'thick', joint: 'joint',
                    boxVal: 'boxval', reserve: 'reserve', rho: 'rho' };
        Object.keys(map).forEach(function (k) {
            var input = $('c-' + map[k]), box = $('e-' + map[k]);
            var msg = errors[k] || '';
            if (k === 'b' && errors.a) { msg = ''; } // a и b делят одно сообщение
            box.textContent = msg;
            if (errors[k]) { input.setAttribute('aria-invalid', 'true'); } else { input.removeAttribute('aria-invalid'); }
        });
        $('e-openings').textContent = errors.openings || '';
        Array.prototype.forEach.call(openList.children, function (row, i) {
            var bad = !!errors['open' + i];
            row.querySelector('.calc-err').textContent = bad ? errors['open' + i] : '';
            Array.prototype.forEach.call(row.querySelectorAll('input'), function (el) {
                if (bad) { el.setAttribute('aria-invalid', 'true'); } else { el.removeAttribute('aria-invalid'); }
            });
        });
    }
    function packsText(packs) {
        return packs.map(function (p) { return p.count + ' уп. по ' + fmt(p.size, 1) + ' кг'; }).join(' или ');
    }
    var MODE_NAMES = { floor: 'пол', walls: 'стены', both: 'пол и стены' };
    function render(r, inp) {
        var res = $('c-result'), bar = $('c-bar');
        if (!r.ok) {
            setErrors(r.errors);
            res.innerHTML = '<p class="calc-wait">Исправьте отмеченные поля — результат появится сразу.</p>';
            $('c-how').innerHTML = '';
            bar.hidden = true;
            lastText = '';
            $('c-copy').disabled = true;
            return;
        }
        setErrors({});
        var boxLine = r.boxes != null ? ', коробок: <strong>' + r.boxes + '</strong>' : '';
        var gl = GROUTS[r.groutKey];
        var bagWord = r.glueBags % 10 === 1 && r.glueBags % 100 !== 11 ? 'мешок' :
            ([2, 3, 4].indexOf(r.glueBags % 10) >= 0 && [12, 13, 14].indexOf(r.glueBags % 100) < 0 ? 'мешка' : 'мешков');
        var html = '<dl class="calc-out">' +
            '<div><dt>Площадь облицовки</dt><dd>' + fmt(r.area) + ' м²</dd></div>' +
            '<div class="calc-main"><dt>Плитка (запас ' + fmt(r.reserve, 1) + ' %)</dt><dd><strong>' + r.pcs + ' шт</strong>' + boxLine + '</dd></div>' +
            '<div><dt>Затирка ' + esc(gl.name) + '</dt><dd><strong>' + fmt(r.groutKg) + ' кг</strong><span class="calc-sub">' + packsText(r.groutPacks) + '</span></dd></div>' +
            '<div><dt>Клей (зуб ' + r.tooth + ' мм)</dt><dd><strong>' + fmt(r.glueKg, 1) + ' кг</strong><span class="calc-sub">' + r.glueBags + ' ' + bagWord + ' по 25 кг</span></dd></div>' +
            '</dl>';
        if (r.bothSidesHint) {
            html += '<p class="calc-note">Большая сторона плитки больше 30 см: клей наносят и на основание, и на плитку, расход при этом больше табличного. Возьмите клея с запасом или уточните норму в инструкции на мешке.</p>';
        }
        if (r.tooth !== r.autoTooth) {
            html += '<p class="calc-note">Зуб выбран вручную; по размеру плитки подходил бы ' + r.autoTooth + ' мм.</p>';
        }
        res.innerHTML = html;
        $('c-how').innerHTML = howText(r, inp);
        bar.hidden = false;
        $('c-bar-text').textContent = 'Плитка: ' + r.pcs + ' шт' + (r.boxes != null ? ', ' + r.boxes + ' кор.' : '');
        lastText = copyText(r);
        $('c-copy').disabled = false;
    }
    function howText(r, inp) {
        var a = toNum(inp.a), b = toNum(inp.b), j = toNum(inp.joint), t = toNum(inp.thick);
        var h = '<ol class="calc-how"><li><strong>Площадь.</strong> ';
        var parts = [];
        if (r.mode !== 'walls') { parts.push('пол ' + fmt(toNum(inp.len)) + '×' + fmt(toNum(inp.wid)) + ' = ' + fmt(r.floorArea) + ' м²'); }
        if (r.mode !== 'floor') {
            parts.push('стены: периметр 2×(' + fmt(toNum(inp.len)) + '+' + fmt(toNum(inp.wid)) + ') = ' + fmt(r.perimeter) +
                ' м, умножить на высоту ' + fmt(toNum(inp.hgt)) + ' м = ' + fmt(r.wallArea) + ' м²');
            parts.push('проёмы: −' + fmt(r.openingsArea) + ' м²');
        }
        h += parts.join('; ') + '. Итого ' + fmt(r.area) + ' м².</li>';
        h += '<li><strong>Плитка.</strong> Одна плитка ' + fmt(a) + '×' + fmt(b) + ' см = ' + fmt(r.tileM2, 4) + ' м². ' +
            fmt(r.area) + ' × (1 + ' + fmt(r.reserve, 1) + '/100) ÷ ' + fmt(r.tileM2, 4) + ' = ' +
            fmt(r.area * (1 + r.reserve / 100) / r.tileM2, 2) + ', округляем вверх: ' + r.pcs + ' шт (без запаса было бы ' + r.pcsNoReserve + ').';
        if (r.boxes != null) {
            h += ' Коробок: ' + (r.boxKind === 'pcs' ? r.pcs + ' ÷ ' + fmt(r.boxVal) : r.pcs + ' × ' + fmt(r.tileM2, 4) + ' ÷ ' + fmt(r.boxVal)) + ' → ' + r.boxes + '.';
        }
        h += '</li>';
        h += '<li><strong>Затирка.</strong> Расход на 1 м² = (A+B)/(A·B) × J × T × ρ = (' + fmt(a * 10) + '+' + fmt(b * 10) + ')/(' +
            fmt(a * 10) + '×' + fmt(b * 10) + ') × ' + fmt(j) + ' × ' + fmt(t) + ' × ' + fmt(r.rho, 2) + ' = ' + fmt(r.groutPerM2, 3) +
            ' кг/м² (A, B — плитка в мм; J — шов, мм; T — толщина, мм; ρ — плотность, кг/дм³). ' +
            'Умножаем на площадь и на 1,1 (запас 10 %): ' + fmt(r.area) + ' × ' + fmt(r.groutPerM2, 3) + ' × 1,1 = ' + fmt(r.groutKg) + ' кг.</li>';
        h += '<li><strong>Клей.</strong> Большая сторона плитки ' + fmt(Math.max(a, b)) + ' см → зуб ' + r.tooth + ' мм, расход ' +
            fmt(r.glueRate, 1) + ' кг/м² (Ceresit CM 11 Plus). ' + fmt(r.area) + ' × ' + fmt(r.glueRate, 1) + ' = ' + fmt(r.glueKg, 1) +
            ' кг → ' + r.glueBags + ' мешк. по 25 кг.</li>';
        return h + '</ol><p class="calc-note">Это оценка: реальный расход зависит от основания, инструмента и укладчика.</p>';
    }
    function copyText(r) {
        var g = GROUTS[r.groutKey];
        return ['Расчёт плитки (' + MODE_NAMES[r.mode] + '), santehrazbor.ru',
            'Площадь: ' + fmt(r.area) + ' м²',
            'Плитка: ' + r.pcs + ' шт (запас ' + fmt(r.reserve, 1) + ' %)' + (r.boxes != null ? ', коробок: ' + r.boxes : ''),
            'Затирка ' + g.name + ': ' + fmt(r.groutKg) + ' кг (' + packsText(r.groutPacks) + ')',
            'Клей, зуб ' + r.tooth + ' мм: ' + fmt(r.glueKg, 1) + ' кг (' + r.glueBags + ' меш. по 25 кг)',
            location.href].join('\n');
    }

    /* --- GoatCounter: не чаще раза в 10 с, только после изменений пользователя --- */
    function countEvent() {
        var now = Date.now();
        if (now - lastCount < 10000) { return; }
        lastCount = now;
        if (window.goatcounter && window.goatcounter.count) {
            window.goatcounter.count({ path: 'calc-plitka', event: true });
        }
    }

    function update(fromUser) {
        syncVisibility();
        var inp = read();
        var r = calc(inp);
        render(r, inp);
        saveUrl(inp);
        if (fromUser && r.ok) { countEvent(); }
    }

    /* --- события --- */
    $('c-preset').addEventListener('change', function () {
        var p = PRESETS[this.value];
        if (p) {
            $('c-a').value = p[0]; $('c-b').value = p[1];
            if (!thickTouched) { $('c-thick').value = p[2]; }
        }
    });
    ['c-a', 'c-b'].forEach(function (id) {
        $(id).addEventListener('input', function () {
            syncPreset();
            var p = PRESETS[$('c-preset').value];
            if (!thickTouched && p) { $('c-thick').value = p[2]; }
        });
    });
    $('c-thick').addEventListener('input', function () { thickTouched = true; });
    // смена раскладки подставляет «обычный» запас; число в поле можно поменять
    form.addEventListener('change', function (e) {
        if (e.target.name === 'layout') { $('c-reserve').value = LAYOUT_RESERVE[e.target.value]; }
    });
    form.addEventListener('input', function () { update(true); });
    form.addEventListener('change', function () { update(true); });
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

    // начальное состояние: из ссылки или значения по умолчанию (ванная 1,7×1,5)
    if (!loadUrl()) { addOpening('door', 0.7, 2.0); }
    wrap.hidden = false;
    update(false);
})(typeof window !== 'undefined' ? window : globalThis);
