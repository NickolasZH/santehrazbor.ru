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
        custom: { name: 'другая затирка', rho: null, packs: [2, 5] }
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
       tub ('1' = под ванной не кладём), tubLen, tubWid (м; только пол), a, b (см), thick, joint (мм), boxKind ('none'|'m2'|'pcs'), boxVal, reserve (%),
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
        // ванна/поддон на полу: площадь под ней вычитается из пола
        var tubOn = useFloor && (inp.tub === true || inp.tub === 1 || inp.tub === '1');
        var tubLen = NaN, tubWid = NaN, tubArea = 0;
        if (tubOn) {
            tubLen = need('tubLen', 'длину ванны', 0.1, 10, 'м');
            tubWid = need('tubWid', 'ширину ванны', 0.1, 10, 'м');
        }
        var floorArea = 0, floorGross = 0, wallArea = 0, perimeter = 0;
        if (!err.len && !err.wid) {
            if (useFloor) { floorGross = len * wid; floorArea = floorGross; }
            perimeter = 2 * (len + wid);
            if (tubOn && !err.tubLen && !err.tubWid) {
                tubArea = tubLen * tubWid;
                if (tubArea >= floorGross) {
                    err.tub = 'Ванна (' + tubArea.toFixed(2).replace('.', ',') + ' м²) не меньше площади пола (' +
                        floorGross.toFixed(2).replace('.', ',') + ' м²): плитки на полу не остаётся. Уменьшите размеры ванны или уберите галочку.';
                } else { floorArea = floorGross - tubArea; }
            }
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
            floorArea: floorArea, floorGross: floorGross, tubOn: tubOn, tubLen: tubLen, tubWid: tubWid, tubArea: tubArea, wallArea: wallArea, openingsArea: openingsArea, area: area,
            tileM2: tileM2, reserve: reserve, pcsNoReserve: ceilEps(area / tileM2), pcs: pcs, boxes: boxes,
            boxKind: boxKind, boxVal: boxVal,
            groutKey: groutKey, rho: rho, groutPerM2: perM2, groutKg: groutKg, groutPacks: packs,
            tooth: tooth, autoTooth: autoTooth, glueRate: rate, glueKg: glueKg,
            glueBags: ceilEps(glueKg / GLUE_BAG_KG), bigTileHint: maxSide > 30 && TEETH.indexOf(toNum(inp.tooth)) < 0
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
            tub: $('c-tub').checked ? '1' : '', tubLen: $('c-tublen').value, tubWid: $('c-tubwid').value,
            openings: readOpenings(), a: $('c-a').value, b: $('c-b').value,
            thick: $('c-thick').value, joint: $('c-joint').value,
            boxKind: $('c-boxkind').value, boxVal: $('c-boxval').value,
            layout: radio('layout'), reserve: $('c-reserve').value,
            groutKey: $('c-grout').value, rho: $('c-rho').value, tooth: $('c-tooth').value
        };
    }

    /* --- состояние в URL --- */
    var KEYS = { mode: 'm', len: 'l', wid: 'w', hgt: 'h', tub: 'tb', tubLen: 'tl', tubWid: 'tw', a: 'a', b: 'b', thick: 't', joint: 'j', boxKind: 'bk', boxVal: 'bv', layout: 'ly', reserve: 'r', groutKey: 'g', rho: 'rho', tooth: 'z' };
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
         ['tl', 'c-tublen'], ['tw', 'c-tubwid'], ['bk', 'c-boxkind'], ['bv', 'c-boxval'], ['r', 'c-reserve'], ['g', 'c-grout'], ['rho', 'c-rho'], ['z', 'c-tooth']].forEach(function (pr) {
            if (p[pr[0]] != null) { $(pr[1]).value = p[pr[0]]; }
        });
        $('c-tub').checked = p.tb === '1';
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
        var custom = $('c-preset').value === 'custom';
        $('c-a-row').hidden = !custom;
        $('c-b-row').hidden = !custom;
        $('c-tub-block').hidden = mode === 'walls';
        $('c-tub-fields').hidden = !$('c-tub').checked;
        $('c-hgt-row').hidden = mode === 'floor';
        $('c-open-block').hidden = mode === 'floor';
        $('c-boxval-row').hidden = $('c-boxkind').value === 'none';
        $('c-boxval-label').textContent = $('c-boxkind').value === 'pcs' ? 'Штук в коробке' : 'Площадь плитки в коробке, м²';
        $('c-rho-row').hidden = $('c-grout').value !== 'custom';
    }

    /* --- подсказки: сантиметры вместо метров и наоборот --- */
    // поля в метрах: значение > 10 и <= 1000 похоже на сантиметры
    var M_FIELDS = ['c-len', 'c-wid', 'c-hgt', 'c-tublen', 'c-tubwid'];
    // размеры плитки в см: значение <= 2 похоже на метры
    var CM_FIELDS = ['c-a', 'c-b'];
    function hintBox(input) {
        var box = input.parentNode.querySelector('.calc-fix');
        if (!box) {
            box = document.createElement('span');
            box.className = 'calc-fix';
            input.parentNode.insertBefore(box, input.nextSibling);
        }
        return box;
    }
    function setHint(input, v, kind) {
        var box = hintBox(input);
        var hidden = !!input.closest('[hidden]');
        if (hidden || isNaN(v)) { box.innerHTML = ''; return; }
        if (kind === 'm' && v > 10 && v <= 1000) {
            box.innerHTML = '<span>Похоже, это сантиметры: ' + fmt(v) + ' см = ' + fmt(v / 100, 3) + ' м</span> ' +
                '<button type="button" class="calc-fixbtn" data-fix="' + input.id + '" data-to="' + fmt(v / 100, 3) + '">Исправить</button>';
        } else if (kind === 'cm' && v > 0 && v <= 2) {
            box.innerHTML = '<span>' + fmt(v) + ' м = ' + fmt(v * 100) + ' см?</span> ' +
                '<button type="button" class="calc-fixbtn" data-fix="' + input.id + '" data-to="' + fmt(v * 100) + '">Исправить</button>';
        } else { box.innerHTML = ''; }
    }
    function renderHints() {
        M_FIELDS.forEach(function (id) { setHint($(id), toNum($(id).value), 'm'); });
        CM_FIELDS.forEach(function (id) { setHint($(id), toNum($(id).value), 'cm'); });
        // проёмы: одна подсказка на строку, по первому подозрительному полю
        Array.prototype.forEach.call(openList.children, function (row) {
            var box = row.querySelector('.calc-fix');
            if (!box) {
                box = document.createElement('span');
                box.className = 'calc-fix';
                row.appendChild(box);
            }
            box.innerHTML = '';
            Array.prototype.some.call(row.querySelectorAll('input'), function (inp) {
                var v = toNum(inp.value);
                if (v > 10 && v <= 1000) {
                    box.innerHTML = '<span>Похоже, это сантиметры: ' + fmt(v) + ' см = ' + fmt(v / 100, 3) + ' м</span> ' +
                        '<button type="button" class="calc-fixbtn" data-fix="' + inp.id + '" data-to="' + fmt(v / 100, 3) + '">Исправить</button>';
                    return true;
                }
                return false;
            });
        });
    }
    form.addEventListener('click', function (e) {
        var id = e.target.getAttribute && e.target.getAttribute('data-fix');
        if (!id) { return; }
        $(id).value = e.target.getAttribute('data-to');
        update(true);
        $(id).focus();
    });

    /* --- вывод --- */
    function setErrors(errors) {
        var map = { len: 'len', wid: 'wid', hgt: 'hgt', a: 'a', b: 'b', thick: 'thick', joint: 'joint',
                    boxVal: 'boxval', reserve: 'reserve', rho: 'rho', tubLen: 'tublen', tubWid: 'tubwid' };
        Object.keys(map).forEach(function (k) {
            var input = $('c-' + map[k]), box = $('e-' + map[k]);
            var msg = errors[k] || '';
            if (k === 'b' && errors.a) { msg = ''; } // a и b делят одно сообщение
            box.textContent = msg;
            if (errors[k]) { input.setAttribute('aria-invalid', 'true'); } else { input.removeAttribute('aria-invalid'); }
        });
        $('e-openings').textContent = errors.openings || '';
        $('e-tub').textContent = errors.tub || '';
        if (errors.tub) { $('c-tublen').setAttribute('aria-invalid', 'true'); $('c-tubwid').setAttribute('aria-invalid', 'true'); }
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
    // поле для ссылки из плашки: ключ ошибки -> [id поля, название]
    var FIELD_NAMES = {
        len: ['c-len', 'длина помещения'], wid: ['c-wid', 'ширина помещения'], hgt: ['c-hgt', 'высота облицовки'],
        tubLen: ['c-tublen', 'длина ванны'], tubWid: ['c-tubwid', 'ширина ванны'], tub: ['c-tublen', 'размеры ванны'],
        a: ['c-a', 'сторона A'], b: ['c-b', 'сторона B'], thick: ['c-thick', 'толщина плитки'], joint: ['c-joint', 'шов'],
        boxVal: ['c-boxval', 'число в коробке'], reserve: ['c-reserve', 'запас'], rho: ['c-rho', 'плотность затирки'],
        openings: ['c-openings', 'проёмы']
    };
    var ERR_ORDER = ['len', 'wid', 'hgt', 'tubLen', 'tubWid', 'tub', 'openings', 'a', 'b', 'thick', 'joint', 'boxVal', 'reserve', 'rho'];
    function showErrorBar(errors) {
        var bar = $('c-bar'), id = null, name = '';
        ERR_ORDER.some(function (k) {
            if (errors[k]) { id = FIELD_NAMES[k][0]; name = FIELD_NAMES[k][1]; return true; }
            return false;
        });
        if (!id) {
            Array.prototype.some.call(openList.children, function (row, i) {
                if (errors['open' + i]) { id = row.querySelector('input').id; name = 'размеры проёма'; return true; }
                return false;
            });
        }
        if (!id) { bar.hidden = true; return; }
        $('c-bar-text').innerHTML = 'Исправьте поле: <a href="#' + id + '" data-focus="' + id + '">' + esc(name) + '</a>';
        $('c-bar-more').hidden = true;
        bar.hidden = false;
    }
    var MODE_NAMES = { floor: 'пол', walls: 'стены', both: 'пол и стены' };
    function render(r, inp) {
        var res = $('c-result'), bar = $('c-bar');
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
        if (r.bigTileHint) {
            html += '<p class="calc-note">По таблице Ceresit CM 11 Plus для плитки больше 30 см — гребёнка 12 мм. Для настенной плитки 25×40 многие мастера берут 10 мм — выберите в списке «Зуб шпателя», расход пересчитается.</p>';
        }
        if (r.tooth !== r.autoTooth) {
            html += '<p class="calc-note">Зуб выбран вручную; по размеру плитки подходил бы ' + r.autoTooth + ' мм.</p>';
        }
        res.innerHTML = html;
        $('c-how').innerHTML = howText(r, inp);
        bar.hidden = false;
        $('c-bar-text').textContent = r.pcs + ' шт' + (r.boxes != null ? ' · ' + r.boxes + ' кор.' : '') +
            ' · затирка ' + fmt(r.groutKg, 1) + ' кг · клей ' + r.glueBags + ' меш.';
        $('c-bar-more').hidden = false;
        lastText = copyText(r);
        $('c-copy').disabled = false;
    }
    function howText(r, inp) {
        var a = toNum(inp.a), b = toNum(inp.b), j = toNum(inp.joint), t = toNum(inp.thick);
        var h = '<ol class="calc-how"><li><strong>Площадь.</strong> ';
        var parts = [];
        if (r.mode !== 'walls') {
            var floorTxt = 'пол ' + fmt(toNum(inp.len)) + '×' + fmt(toNum(inp.wid)) + ' = ' + fmt(r.floorGross) + ' м²';
            if (r.tubOn) {
                floorTxt += ', под ванной ' + fmt(r.tubLen) + '×' + fmt(r.tubWid) + ' = −' + fmt(r.tubArea) + ' м², пол с вычетом ' + fmt(r.floorArea) + ' м²';
            }
            parts.push(floorTxt);
        }
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
            'Площадь: ' + fmt(r.area) + ' м²' + (r.tubOn ? ' (без пола под ванной ' + fmt(r.tubLen) + '×' + fmt(r.tubWid) + ' м: −' + fmt(r.tubArea) + ' м²)' : ''),
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
        renderHints();
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
    // A/B правятся только при «Свой размер», поэтому список от них не зависит (иначе поля пропали бы при вводе 25 и 40)
    $('c-thick').addEventListener('input', function () { thickTouched = true; });
    // смена раскладки подставляет «обычный» запас; число в поле можно поменять
    form.addEventListener('change', function (e) {
        if (e.target.name === 'layout') { $('c-reserve').value = LAYOUT_RESERVE[e.target.value]; }
    });
    form.addEventListener('input', function () { update(true); });
    form.addEventListener('change', function () { update(true); });
    // плашка: ссылка на поле с ошибкой — прокрутить и поставить фокус
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

    // начальное состояние: из ссылки или значения по умолчанию (ванная 1,7×1,5)
    if (!loadUrl()) { addOpening('door', 0.7, 2.0); }
    wrap.hidden = false;
    update(false);
})(typeof window !== 'undefined' ? window : globalThis);
