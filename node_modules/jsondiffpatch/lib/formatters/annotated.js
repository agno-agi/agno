import BaseFormatter from './base.js';
class AnnotatedFormatter extends BaseFormatter {
    constructor() {
        super();
        this.includeMoveDestinations = false;
    }
    prepareContext(context) {
        super.prepareContext(context);
        context.indent = function (levels) {
            this.indentLevel =
                (this.indentLevel || 0) + (typeof levels === 'undefined' ? 1 : levels);
            this.indentPad = new Array(this.indentLevel + 1).join('&nbsp;&nbsp;');
        };
        context.row = (json, htmlNote) => {
            context.out('<tr><td style="white-space: nowrap;">' +
                '<pre class="jsondiffpatch-annotated-indent"' +
                ' style="display: inline-block">');
            if (context.indentPad != null)
                context.out(context.indentPad);
            context.out('</pre><pre style="display: inline-block">');
            context.out(json);
            context.out('</pre></td><td class="jsondiffpatch-delta-note"><div>');
            if (htmlNote != null)
                context.out(htmlNote);
            context.out('</div></td></tr>');
        };
    }
    typeFormattterErrorFormatter(context, err) {
        // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
        context.row('', `<pre class="jsondiffpatch-error">${err}</pre>`);
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
                context.out(`<span class="jsondiffpatch-textdiff-${piece.type}">${piece.text}</span>`);
            }
            context.out('</div></li>');
        }
        context.out('</ul>');
    }
    rootBegin(context, type, nodeType) {
        context.out('<table class="jsondiffpatch-annotated-delta">');
        if (type === 'node') {
            context.row('{');
            context.indent();
        }
        if (nodeType === 'array') {
            context.row('"_t": "a",', 'Array delta (member names indicate array indices)');
        }
    }
    rootEnd(context, type) {
        if (type === 'node') {
            context.indent(-1);
            context.row('}');
        }
        context.out('</table>');
    }
    nodeBegin(context, key, leftKey, type, nodeType) {
        context.row(`&quot;${key}&quot;: {`);
        if (type === 'node') {
            context.indent();
        }
        if (nodeType === 'array') {
            context.row('"_t": "a",', 'Array delta (member names indicate array indices)');
        }
    }
    nodeEnd(context, key, leftKey, type, nodeType, isLast) {
        if (type === 'node') {
            context.indent(-1);
        }
        context.row(`}${isLast ? '' : ','}`);
    }
    format_unchanged() { }
    format_movedestination() { }
    format_node(context, delta, left) {
        // recurse
        this.formatDeltaChildren(context, delta, left);
    }
    format_added(context, delta, left, key, leftKey) {
        formatAnyChange.call(this, context, delta, left, key, leftKey);
    }
    format_modified(context, delta, left, key, leftKey) {
        formatAnyChange.call(this, context, delta, left, key, leftKey);
    }
    format_deleted(context, delta, left, key, leftKey) {
        formatAnyChange.call(this, context, delta, left, key, leftKey);
    }
    format_moved(context, delta, left, key, leftKey) {
        formatAnyChange.call(this, context, delta, left, key, leftKey);
    }
    format_textdiff(context, delta, left, key, leftKey) {
        formatAnyChange.call(this, context, delta, left, key, leftKey);
    }
}
const wrapPropertyName = (name) => `<pre style="display:inline-block">&quot;${name}&quot;</pre>`;
const deltaAnnotations = {
    added(delta, left, key, leftKey) {
        const formatLegend = ' <pre>([newValue])</pre>';
        if (typeof leftKey === 'undefined') {
            return `new value${formatLegend}`;
        }
        if (typeof leftKey === 'number') {
            return `insert at index ${leftKey}${formatLegend}`;
        }
        return `add property ${wrapPropertyName(leftKey)}${formatLegend}`;
    },
    modified(delta, left, key, leftKey) {
        const formatLegend = ' <pre>([previousValue, newValue])</pre>';
        if (typeof leftKey === 'undefined') {
            return `modify value${formatLegend}`;
        }
        if (typeof leftKey === 'number') {
            return `modify at index ${leftKey}${formatLegend}`;
        }
        return `modify property ${wrapPropertyName(leftKey)}${formatLegend}`;
    },
    deleted(delta, left, key, leftKey) {
        const formatLegend = ' <pre>([previousValue, 0, 0])</pre>';
        if (typeof leftKey === 'undefined') {
            return `delete value${formatLegend}`;
        }
        if (typeof leftKey === 'number') {
            return `remove index ${leftKey}${formatLegend}`;
        }
        return `delete property ${wrapPropertyName(leftKey)}${formatLegend}`;
    },
    moved(delta, left, key, leftKey) {
        return ('move from <span title="(position to remove at original state)">' +
            `index ${leftKey}</span> to <span title="(position to insert at final` +
            ` state)">index ${delta[1]}</span>`);
    },
    textdiff(delta, left, key, leftKey) {
        const location = typeof leftKey === 'undefined'
            ? ''
            : typeof leftKey === 'number'
                ? ` at index ${leftKey}`
                : ` at property ${wrapPropertyName(leftKey)}`;
        return (`text diff${location}, format is <a href="https://code.google.com/` +
            'p/google-diff-match-patch/wiki/Unidiff">a variation of Unidiff</a>');
    },
};
const formatAnyChange = function (context, delta, left, key, leftKey) {
    const deltaType = this.getDeltaType(delta);
    const annotator = deltaAnnotations[deltaType];
    const htmlNote = annotator && annotator(delta, left, key, leftKey);
    let json = JSON.stringify(delta, null, 2);
    if (deltaType === 'textdiff') {
        // split text diffs lines
        json = json.split('\\n').join('\\n"+\n   "');
    }
    context.indent();
    context.row(json, htmlNote);
    context.indent(-1);
};
export default AnnotatedFormatter;
let defaultInstance;
export function format(delta, left) {
    if (!defaultInstance) {
        defaultInstance = new AnnotatedFormatter();
    }
    return defaultInstance.format(delta, left);
}
