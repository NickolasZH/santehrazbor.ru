// Сниппет для консоли браузера: узнать реферальную награду по карточкам Маркета.
// Запускать на вкладке market.yandex.ru при выполненном входе (награду Маркет отдаёт только залогиненному).
// 1) заполните URLS ссылками на карточки (поле url из affiliate.json);
// 2) вставьте скрипт в консоль (F12 -> Console) и дождитесь JSON в конце;
// 3) значения запишите в affiliate.json как reward_rub_<ГГГГ_ММ_ДД>.
(async () => {
    const URLS = [
        // "https://market.yandex.ru/card/.../103812659581",
    ];
    const RE = /referralReward(?:&quot;|\\?")?:\s*(\d+)/;
    const result = {};
    for (const url of URLS) {
        try {
            const text = await fetch(url).then(r => r.text());
            const m = text.match(RE);
            result[url] = m ? Number(m[1]) : 0; // нет совпадения — награды нет
        } catch (err) {
            result[url] = null; // ошибка запроса — повторить вручную
            console.warn("Ошибка", url, err);
        }
        await new Promise(r => setTimeout(r, 1500));
    }
    console.log(JSON.stringify(result));
})();
