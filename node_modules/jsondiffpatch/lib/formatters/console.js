import chalk from 'chalk';
import BaseFormatter from './base.js';
const colors = {
    added: chalk.green,
    deleted: chalk.red,
    movedestination: chalk.gray,
    moved: chalk.yellow,
    unchanged: chalk.gray,
    error: chalk.white.bgRed,
    textDiffLine: chalk.gray,
};
class ConsoleFormatter extends BaseFormatter {
    constructor() {
        super();
        this.includeMoveDestinations = false;
    }
    prepareContext(context) {
        super.prepareContext(context);
        context.indent = function (levels) {
            this.indentLevel =
                (this.indentLevel || 0) + (typeof levels === 'undefined' ? 1 : levels);
            this.indentPad = new Array(this.indentLevel + 1).join('  ');
            this.outLine();
        };
        context.outLine = function () {
            this.buffer.push(`\n${this.indentPad || ''}`);
        };
        context.out = function (...args) {
            for (let i = 0, l = args.length; i < l; i++) {
                const lines = args[i].split('\n');
                let text = lines.join(`\n${this.indentPad || ''}`);
                if (this.color && this.color[0]) {
                    text = this.color[0](text);
                }
                this.buffer.push(text);
            }
        };
        context.pushColor = function (color) {
            this.color = this.color || [];
            this.color.unshift(color);
        };
        context.popColor = function () {
            this.color = this.color || [];
            this.color.shift();
        };
    }
    typeFormattterErrorFormatter(context, err) {
        context.pushColor(colors.error);
        // eslint-disable-next-line @typescript-eslint/restrict-template-expressions
        context.out(`[ERROR]${err}`);
        context.popColor();
    }
    formatValue(context, value) {
        context.out(JSON.stringify(value, null, 2));
    }
    formatTextDiffString(context, value) {
        const lines = this.parseTextDiff(value);
        context.indent();
        for (let i = 0, l = lines.length; i < l; i++) {
            const line = lines[i];
            context.pushColor(colors.textDiffLine);
            context.out(`${line.location.line},${line.location.chr} `);
            context.popColor();
            const pieces = line.pieces;
            for (let pieceIndex = 0, piecesLength = pieces.length; pieceIndex < piecesLength; pieceIndex++) {
                const piece = pieces[pieceIndex];
                context.pushColor(colors[piece.type]);
                context.out(piece.text);
                context.popColor();
            }
            if (i < l - 1) {
                context.outLine();
            }
        }
        context.indent(-1);
    }
    rootBegin(context, type, nodeType) {
        context.pushColor(colors[type]);
        if (type === 'node') {
            context.out(nodeType === 'array' ? '[' : '{');
            context.indent();
        }
    }
    rootEnd(context, type, nodeType) {
        if (type === 'node') {
            context.indent(-1);
            context.out(nodeType === 'array' ? ']' : '}');
        }
        context.popColor();
    }
    nodeBegin(context, key, leftKey, type, nodeType) {
        context.pushColor(colors[type]);
        context.out(`${leftKey}: `);
        if (type === 'node') {
            context.out(nodeType === 'array' ? '[' : '{');
            context.indent();
        }
    }
    nodeEnd(context, key, leftKey, type, nodeType, isLast) {
        if (type === 'node') {
            context.indent(-1);
            context.out(nodeType === 'array' ? ']' : `}${isLast ? '' : ','}`);
        }
        if (!isLast) {
            context.outLine();
        }
        context.popColor();
    }
    format_unchanged(context, delta, left) {
        if (typeof left === 'undefined') {
            return;
        }
        this.formatValue(context, left);
    }
    format_movedestination(context, delta, left) {
        if (typeof left === 'undefined') {
            return;
        }
        this.formatValue(context, left);
    }
    format_node(context, delta, left) {
        // recurse
        this.formatDeltaChildren(context, delta, left);
    }
    format_added(context, delta) {
        this.formatValue(context, delta[0]);
    }
    format_modified(context, delta) {
        context.pushColor(colors.deleted);
        this.formatValue(context, delta[0]);
        context.popColor();
        context.out(' => ');
        context.pushColor(colors.added);
        this.formatValue(context, delta[1]);
        context.popColor();
    }
    format_deleted(context, delta) {
        this.formatValue(context, delta[0]);
    }
    format_moved(context, delta) {
        context.out(`==> ${delta[1]}`);
    }
    format_textdiff(context, delta) {
        this.formatTextDiffString(context, delta[0]);
    }
}
export default ConsoleFormatter;
let defaultInstance;
export const format = (delta, left) => {
    if (!defaultInstance) {
        defaultInstance = new ConsoleFormatter();
    }
    return defaultInstance.format(delta, left);
};
export function log(delta, left) {
    console.log(format(delta, left));
}
