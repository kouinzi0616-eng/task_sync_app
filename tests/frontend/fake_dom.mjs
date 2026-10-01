// ============================================================
// 最小の偽 DOM（node だけで frontend/app.js を動かして確かめるため）
// - index.html を読んで木を作る（このアプリの HTML が読めれば十分な、小さな読み取り）
// - app.js が使う分だけの DOM の機能を持つ
// - HTML として解釈させる書き方（inner/outer HTML・insertAdjacentHTML）は記録して例外にする
// ブラウザそのものではないので、見た目や読み上げは確かめられない。
// ============================================================

const VOID_TAGS = new Set(['meta', 'link', 'br', 'img', 'input', 'hr', 'source']);

export class FakeEvent {
    constructor(type, init = {}) {
        this.type = type;
        this.bubbles = false;
        this.defaultPrevented = false;
        this.propagationStopped = false;
        Object.assign(this, init);
    }

    preventDefault() {
        this.defaultPrevented = true;
    }

    stopPropagation() {
        this.propagationStopped = true;
    }
}

class FakeNode {
    constructor(doc) {
        this.ownerDocument = doc;
        this.parentNode = null;
        this.childNodes = [];
        this.listeners = {};
    }

    appendChild(child) {
        if (!(child instanceof FakeNode)) throw new TypeError('appendChild には要素か文字のノードを渡す');
        if (child.parentNode) child.parentNode.removeChild(child);
        child.parentNode = this;
        this.childNodes.push(child);
        return child;
    }

    removeChild(child) {
        const index = this.childNodes.indexOf(child);
        if (index >= 0) this.childNodes.splice(index, 1);
        child.parentNode = null;
        return child;
    }

    append(...items) {
        for (const item of items) {
            this.appendChild(typeof item === 'string' ? this.ownerDocument.createTextNode(item) : item);
        }
    }

    replaceChildren(...items) {
        for (const child of this.childNodes.slice()) this.removeChild(child);
        this.append(...items);
    }

    remove() {
        if (this.parentNode) this.parentNode.removeChild(this);
    }

    get textContent() {
        return this.childNodes.map(child => child.textContent).join('');
    }

    set textContent(value) {
        for (const child of this.childNodes.slice()) this.removeChild(child);
        if (value !== null && value !== undefined && value !== '') {
            this.appendChild(this.ownerDocument.createTextNode(String(value)));
        }
    }

    addEventListener(type, listener) {
        (this.listeners[type] ||= []).push(listener);
    }

    removeEventListener(type, listener) {
        const list = this.listeners[type] || [];
        const index = list.indexOf(listener);
        if (index >= 0) list.splice(index, 1);
    }

    dispatchEvent(event) {
        if (!event.target) event.target = this;
        let node = this;
        while (node) {
            event.currentTarget = node;
            for (const listener of (node.listeners[event.type] || []).slice()) listener.call(node, event);
            if (!event.bubbles || event.propagationStopped) break;
            node = node.parentNode;
        }
        return !event.defaultPrevented;
    }
}

class FakeText extends FakeNode {
    constructor(doc, data) {
        super(doc);
        this.nodeType = 3;
        this.data = String(data);
    }

    get textContent() {
        return this.data;
    }

    set textContent(value) {
        this.data = String(value);
    }
}

// 単純なセレクタ（tag・#id・.class・[attr]・[attr="値"]）と、空白でつないだ子孫の指定だけ
function parseCompound(text) {
    const parts = { tag: null, id: null, classes: [], attrs: [] };
    const re = /([a-zA-Z][\w-]*)|#([\w-]+)|\.([\w-]+)|\[([\w-]+)(?:="([^"]*)")?\]/g;
    let match;
    let consumed = 0;
    while ((match = re.exec(text)) !== null) {
        if (match.index !== consumed) throw new Error(`読めないセレクタ: ${text}`);
        consumed = re.lastIndex;
        if (match[1]) parts.tag = match[1].toUpperCase();
        else if (match[2]) parts.id = match[2];
        else if (match[3]) parts.classes.push(match[3]);
        else parts.attrs.push([match[4], match[5]]);
    }
    if (consumed !== text.length) throw new Error(`読めないセレクタ: ${text}`);
    return parts;
}

function matchesCompound(element, parts) {
    if (parts.tag && element.tagName !== parts.tag) return false;
    if (parts.id && element.id !== parts.id) return false;
    for (const name of parts.classes) if (!element.classList.contains(name)) return false;
    for (const [name, value] of parts.attrs) {
        if (!element.hasAttribute(name)) return false;
        if (value !== undefined && element.getAttribute(name) !== value) return false;
    }
    return true;
}

function matchesSelector(element, selector) {
    return selector.split(',').some(alternative => {
        const chain = alternative.trim().split(/\s+/).map(parseCompound);
        if (!matchesCompound(element, chain[chain.length - 1])) return false;
        let node = element.parentNode;
        for (let i = chain.length - 2; i >= 0; i--) {
            while (node && !(node instanceof FakeElement && matchesCompound(node, chain[i]))) node = node.parentNode;
            if (!node) return false;
            node = node.parentNode;
        }
        return true;
    });
}

function descendants(root) {
    const out = [];
    const walk = node => {
        for (const child of node.childNodes) {
            if (child instanceof FakeElement) {
                out.push(child);
                walk(child);
            }
        }
    };
    walk(root);
    return out;
}

export class FakeElement extends FakeNode {
    constructor(doc, tagName) {
        super(doc);
        this.nodeType = 1;
        this.tagName = tagName.toUpperCase();
        this.attributes = new Map();
        this.style = {};
        this._value = null;
    }

    getAttribute(name) {
        name = name.toLowerCase();
        return this.attributes.has(name) ? this.attributes.get(name) : null;
    }

    setAttribute(name, value) {
        name = name.toLowerCase();
        if (name.startsWith('on')) {
            this.ownerDocument.htmlSinkUses.push(`setAttribute(${name})`);
            throw new Error('イベント属性は使わない');
        }
        this.attributes.set(name, String(value));
    }

    removeAttribute(name) {
        this.attributes.delete(name.toLowerCase());
    }

    hasAttribute(name) {
        return this.attributes.has(name.toLowerCase());
    }

    get id() {
        return this.getAttribute('id') || '';
    }

    set id(value) {
        this.setAttribute('id', value);
    }

    get className() {
        return this.getAttribute('class') || '';
    }

    set className(value) {
        this.setAttribute('class', value);
    }

    get classList() {
        const element = this;
        const read = () => element.className.split(/\s+/).filter(Boolean);
        const write = list => element.setAttribute('class', list.join(' '));
        return {
            add: (...names) => write([...new Set([...read(), ...names])]),
            remove: (...names) => write(read().filter(n => !names.includes(n))),
            contains: name => read().includes(name),
            toggle: (name, force) => {
                const has = read().includes(name);
                const want = force === undefined ? !has : force;
                if (want && !has) write([...read(), name]);
                if (!want && has) write(read().filter(n => n !== name));
                return want;
            }
        };
    }

    get dataset() {
        const data = {};
        for (const [name, value] of this.attributes) {
            if (name.startsWith('data-')) {
                data[name.slice(5).replace(/-([a-z])/g, (_, c) => c.toUpperCase())] = value;
            }
        }
        return data;
    }

    get hidden() {
        return this.hasAttribute('hidden');
    }

    set hidden(value) {
        if (value) this.setAttribute('hidden', '');
        else this.removeAttribute('hidden');
    }

    get disabled() {
        return this.hasAttribute('disabled');
    }

    set disabled(value) {
        if (value) this.setAttribute('disabled', '');
        else this.removeAttribute('disabled');
    }

    get value() {
        if (this._value !== null) return this._value;
        return this.tagName === 'TEXTAREA' ? this.textContent : (this.getAttribute('value') || '');
    }

    set value(text) {
        this._value = String(text);
    }

    get children() {
        return this.childNodes.filter(node => node instanceof FakeElement);
    }

    focus() {
        this.ownerDocument.activeElement = this;
    }

    // 入力欄の文字をすべて選ぶ（コピーの控えの欄で使う）
    select() {
        this.ownerDocument.selectedElement = this;
    }

    click() {
        this.dispatchEvent(new FakeEvent('click', { bubbles: true }));
    }

    matches(selector) {
        return matchesSelector(this, selector);
    }

    closest(selector) {
        let node = this;
        while (node instanceof FakeElement) {
            if (node.matches(selector)) return node;
            node = node.parentNode;
        }
        return null;
    }

    querySelectorAll(selector) {
        return descendants(this).filter(element => element.matches(selector));
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    // HTML として解釈させる書き方は、使ったら記録して止める
    get innerHTML() {
        return '';
    }

    set innerHTML(value) {
        this.ownerDocument.htmlSinkUses.push(`innerHTML = ${String(value).slice(0, 80)}`);
        throw new Error('innerHTML への代入は使わない');
    }

    set outerHTML(value) {
        this.ownerDocument.htmlSinkUses.push(`outerHTML = ${String(value).slice(0, 80)}`);
        throw new Error('outerHTML への代入は使わない');
    }

    insertAdjacentHTML(position, value) {
        this.ownerDocument.htmlSinkUses.push(`insertAdjacentHTML(${position}) ${String(value).slice(0, 80)}`);
        throw new Error('insertAdjacentHTML は使わない');
    }
}

export class FakeDocument extends FakeNode {
    constructor() {
        super(null);
        this.ownerDocument = this;
        this.nodeType = 9;
        this.readyState = 'complete';
        this.activeElement = null;
        this.createdTags = [];   // app.js が createElement で作った要素の名前
        this.htmlSinkUses = [];  // HTML として解釈させる書き方を使った記録
    }

    createElement(tag) {
        const element = new FakeElement(this, tag);
        this.createdTags.push(element.tagName);
        return element;
    }

    createTextNode(text) {
        return new FakeText(this, text);
    }

    get documentElement() {
        return this.children[0] || null;
    }

    get children() {
        return this.childNodes.filter(node => node instanceof FakeElement);
    }

    get body() {
        return this.querySelector('body');
    }

    getElementById(id) {
        return descendants(this).find(element => element.id === id) || null;
    }

    querySelectorAll(selector) {
        return descendants(this).filter(element => element.matches(selector));
    }

    querySelector(selector) {
        return this.querySelectorAll(selector)[0] || null;
    }

    allElements() {
        return descendants(this);
    }

    write() {
        this.htmlSinkUses.push('document.write');
        throw new Error('document.write は使わない');
    }
}

function decodeEntities(text) {
    return text
        .replace(/&#(\d+);/g, (_, n) => String.fromCodePoint(Number(n)))
        .replace(/&#x([0-9a-fA-F]+);/g, (_, n) => String.fromCodePoint(parseInt(n, 16)))
        .replace(/&quot;/g, '"')
        .replace(/&lt;/g, '<')
        .replace(/&gt;/g, '>')
        .replace(/&amp;/g, '&');
}

// index.html を読んで木を作る（属性の値は "..." だけ）
export function parseHTML(doc, html) {
    html = html.replace(/<!--[\s\S]*?-->/g, '').replace(/<!DOCTYPE[^>]*>/i, '');
    const tokenRe = /<\/([a-zA-Z][\w-]*)\s*>|<([a-zA-Z][\w-]*)((?:\s+[^\s=>]+(?:\s*=\s*"[^"]*")?)*)\s*\/?>|([^<]+)/g;
    const attrRe = /([^\s=>]+)(?:\s*=\s*"([^"]*)")?/g;
    const stack = [doc];
    let match;
    while ((match = tokenRe.exec(html)) !== null) {
        const [, closing, opening, attrText, text] = match;
        const parent = stack[stack.length - 1];
        if (text !== undefined) {
            parent.appendChild(new FakeText(doc, decodeEntities(text)));
        } else if (opening) {
            const element = new FakeElement(doc, opening);
            let attr;
            attrRe.lastIndex = 0;
            while ((attr = attrRe.exec(attrText || '')) !== null) {
                element.attributes.set(attr[1].toLowerCase(), attr[2] === undefined ? '' : decodeEntities(attr[2]));
            }
            parent.appendChild(element);
            if (!VOID_TAGS.has(opening.toLowerCase())) stack.push(element);
        } else if (closing) {
            const tag = closing.toUpperCase();
            while (stack.length > 1) {
                const top = stack.pop();
                if (top.tagName === tag) break;
            }
        }
    }
    return doc;
}
