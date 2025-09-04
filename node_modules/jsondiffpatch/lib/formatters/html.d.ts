import BaseFormatter from './base.js';
import type { BaseFormatterContext, DeltaType, NodeType } from './base.js';
import type { AddedDelta, ArrayDelta, DeletedDelta, Delta, ModifiedDelta, MovedDelta, ObjectDelta, TextDiffDelta } from '../types.js';
interface HtmlFormatterContext extends BaseFormatterContext {
    hasArrows?: boolean;
}
declare class HtmlFormatter extends BaseFormatter<HtmlFormatterContext> {
    typeFormattterErrorFormatter(context: HtmlFormatterContext, err: unknown): void;
    formatValue(context: HtmlFormatterContext, value: unknown): void;
    formatTextDiffString(context: HtmlFormatterContext, value: string): void;
    rootBegin(context: HtmlFormatterContext, type: DeltaType, nodeType: NodeType): void;
    rootEnd(context: HtmlFormatterContext): void;
    nodeBegin(context: HtmlFormatterContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType): void;
    nodeEnd(context: HtmlFormatterContext): void;
    format_unchanged(context: HtmlFormatterContext, delta: undefined, left: unknown): void;
    format_movedestination(context: HtmlFormatterContext, delta: undefined, left: unknown): void;
    format_node(context: HtmlFormatterContext, delta: ObjectDelta | ArrayDelta, left: unknown): void;
    format_added(context: HtmlFormatterContext, delta: AddedDelta): void;
    format_modified(context: HtmlFormatterContext, delta: ModifiedDelta): void;
    format_deleted(context: HtmlFormatterContext, delta: DeletedDelta): void;
    format_moved(context: HtmlFormatterContext, delta: MovedDelta): void;
    format_textdiff(context: HtmlFormatterContext, delta: TextDiffDelta): void;
}
export declare const showUnchanged: (show?: boolean, node?: Element | null, delay?: number) => void;
export declare const hideUnchanged: (node?: Element, delay?: number) => void;
export default HtmlFormatter;
export declare function format(delta: Delta, left?: unknown): string | undefined;
