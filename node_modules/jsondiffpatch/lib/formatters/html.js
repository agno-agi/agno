import BaseFormatter from './base.js';
class HtmlFormatter extends BaseFormatter {
    typeFormattterErrorFormatter(context, err) {
        // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
        context.out(`<pre class="jsondiffpatch-error">${err}</pre>`);
    }
    formatValue(context, value) {
        context.out(`<pre>${htmlEscape(JSON.stringify(value, null, 2))}</pre>`);
    }
    formatTextDiffString(context, value) {
        const lines = this.parseTextDiff(value);
        context.out('<ul class="jsondiffpatch-textdiff">');
        for (let i = 0, l = lines.length; i < l; i++) {
            const line = lines[i];
            context.out('<li><div class="jsondiffpatch-textdiff-location">' +
                `<span class="jsondiffpatch-textdiff-line-number">${line.location.line}</span><span class="jsondiffpatch-textdiff-char">${line.location.chr}</span></div><div class="jsondiffpatch-textdiff-line">`);
            const pieces = line.pieces;
            for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
                const piece = pieces[pieceIndex];
                context.out(`<span class="jsondiffpatch-textdiff-${piece.type}">${htmlEscape(decodeURI(piece.text))}</span>`);
            }
            context.out('</div></li>');
        }
        context.out('</ul>');
    }
    rootBegin(context, type, nodeType) {
        const nodeClass = `jsondiffpatch-${type}${nodeType ? ` jsondiffpatch-child-node-type-${nodeType}` : ''}`;
        context.out(`<div class="jsondiffpatch-delta ${nodeClass}">`);
    }
    rootEnd(context) {
        context.out(`</div>${context.hasArrows
            ? '<script type="text/javascript">setTimeout(' +
                `${adjustArrows.toString()},10);</script>`
            : ''}`);
    }
    nodeBegin(context, key, leftKey, type, nodeType) {
        const nodeClass = `jsondiffpatch-${type}${nodeType ? ` jsondiffpatch-child-node-type-${nodeType}` : ''}`;
        context.out(`<li class="${nodeClass}" data-key="${leftKey}">` +
            `<div class="jsondiffpatch-property-name">${leftKey}</div>`);
    }
    nodeEnd(context) {
        context.out('</li>');
    }
    format_unchanged(context, delta, left) {
        if (typeof left === 'undefined') {
            return;
        }
        context.out('<div class="jsondiffpatch-value">');
        this.formatValue(context, left);
        context.out('</div>');
    }
    format_movedestination(context, delta, left) {
        if (typeof left === 'undefined') {
            return;
        }
        context.out('<div class="jsondiffpatch-value">');
        this.formatValue(context, left);
        context.out('</div>');
    }
    format_node(context, delta, left) {
        // recurse
        const nodeType = delta._t === 'a' ? 'array' : 'object';
        context.out(`<ul class="jsondiffpatch-node jsondiffpatch-node-type-${nodeType}">`);
        this.formatDeltaChildren(context, delta, left);
        context.out('</ul>');
    }
    format_added(context, delta) {
        context.out('<div class="jsondiffpatch-value">');
        this.formatValue(context, delta[0]);
        context.out('</div>');
    }
    format_modified(context, delta) {
        context.out('<div class="jsondiffpatch-value jsondiffpatch-left-value">');
        this.formatValue(context, delta[0]);
        context.out('</div>' + '<div class="jsondiffpatch-value jsondiffpatch-right-value">');
        this.formatValue(context, delta[1]);
        context.out('</div>');
    }
    format_deleted(context, delta) {
        context.out('<div class="jsondiffpatch-value">');
        this.formatValue(context, delta[0]);
        context.out('</div>');
    }
    format_moved(context, delta) {
        context.out('<div class="jsondiffpatch-value">');
        this.formatValue(context, delta[0]);
        context.out(`</div><div class="jsondiffpatch-moved-destination">${delta[1]}</div>`);
        // draw an SVG arrow from here to move destination
        context.out(
        /* jshint multistr: true */
        '<div class="jsondiffpatch-arrow" ' +
            `style="position: relative; left: -34px;">
          <svg width="30" height="60" ` +
            `style="position: absolute; display: none;">
          <defs>
              <marker id="markerArrow" markerWidth="8" markerHeight="8"
                 refx="2" refy="4"
                     orient="auto" markerUnits="userSpaceOnUse">
                  <path d="M1,1 L1,7 L7,4 L1,1" style="fill: #339;" />
              </marker>
          </defs>
          <path d="M30,0 Q-10,25 26,50"
            style="stroke: #88f; stroke-width: 2px; fill: none; ` +
            `stroke-opacity: 0.5; marker-end: url(#markerArrow);"
          ></path>
          </svg>
      </div>`);
        context.hasArrows = true;
    }
    format_textdiff(context, delta) {
        context.out('<div class="jsondiffpatch-value">');
        this.formatTextDiffString(context, delta[0]);
        context.out('</div>');
    }
}
function htmlEscape(text) {
    let html = text;
    const replacements = [
        [/&/g, '&amp;'],
        [/</g, '&lt;'],
        [/>/g, '&gt;'],
        [/'/g, '&apos;'],
        [/"/g, '&quot;'],
    ];
    for (let i = 0; i < replacements.length; i++) {
        html = html.replace(replacements[i][0], replacements[i][1]);
    }
    return html;
}
const adjustArrows = function jsondiffpatchHtmlFormatterAdjustArrows(nodeArg) {
    const node = nodeArg || document;
    const getElementText = ({ textContent, innerText }) => textContent || innerText;
    const eachByQuery = (el, query, fn) => {
        const elems = el.querySelectorAll(query);
        for (let i = 0, l = elems.length; i < l; i++) {
            fn(elems[i]);
        }
    };
    const eachChildren = ({ children }, fn) => {
        for (let i = 0, l = children.length; i < l; i++) {
            fn(children[i], i);
        }
    };
    eachByQuery(node, '.jsondiffpatch-arrow', ({ parentNode, children, style }) => {
        const arrowParent = parentNode;
        const svg = children[0];
        const path = svg.children[1];
        svg.style.display = 'none';
        const destination = getElementText(arrowParent.querySelector('.jsondiffpatch-moved-destination'));
        const container = arrowParent.parentNode;
        let destinationElem;
        eachChildren(container, (child) => {
            if (child.getAttribute('data-key') === destination) {
                destinationElem = child;
            }
        });
        if (!destinationElem) {
            return;
        }
        try {
            const distance = destinationElem.offsetTop - arrowParent.offsetTop;
            svg.setAttribute('height', `${Math.abs(distance) + 6}`);
            style.top = `${-8 + (distance > 0 ? 0 : distance)}px`;
            const curve = distance > 0
                ? `M30,0 Q-10,${Math.round(distance / 2)} 26,${distance - 4}`
                : `M30,${-distance} Q-10,${Math.round(-distance / 2)} 26,4`;
            path.setAttribute('d', curve);
            svg.style.display = '';
        }
        catch (err) {
            // continue regardless of error
        }
    });
};
export const showUnchanged = (show, node, delay) => {
    const el = node || document.body;
    const prefix = 'jsondiffpatch-unchanged-';
    const classes = {
        showing: `${prefix}showing`,
        hiding: `${prefix}hiding`,
        visible: `${prefix}visible`,
        hidden: `${prefix}hidden`,
    };
    const list = el.classList;
    if (!list) {
        return;
    }
    if (!delay) {
        list.remove(classes.showing);
        list.remove(classes.hiding);
        list.remove(classes.visible);
        list.remove(classes.hidden);
        if (show === false) {
            list.add(classes.hidden);
        }
        return;
    }
    if (show === false) {
        list.remove(classes.showing);
        list.add(classes.visible);
        setTimeout(() => {
            list.add(classes.hiding);
        }, 10);
    }
    else {
        list.remove(classes.hiding);
        list.add(classes.showing);
        list.remove(classes.hidden);
    }
    const intervalId = setInterval(() => {
        adjustArrows(el);
    }, 100);
    setTimeout(() => {
        list.remove(classes.showing);
        list.remove(classes.hiding);
        if (show === false) {
            list.add(classes.hidden);
            list.remove(classes.visible);
        }
        else {
            list.add(classes.visible);
            list.remove(classes.hidden);
        }
        setTimeout(() => {
            list.remove(classes.visible);
            clearInterval(intervalId);
        }, delay + 400);
    }, delay);
};
export const hideUnchanged = (node, delay) => showUnchanged(false, node, delay);
export default HtmlFormatter;
let defaultInstance;
export function format(delta, left) {
    if (!defaultInstance) {
        defaultInstance = new HtmlFormatter();
    }
    return defaultInstance.format(delta, left);
}
