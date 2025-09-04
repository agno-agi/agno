import BaseFormatter from './base.js';
import type { BaseFormatterContext, DeltaType, NodeType } from './base.js';
import type { AddedDelta, ArrayDelta, DeletedDelta, Delta, ModifiedDelta, MovedDelta, ObjectDelta, TextDiffDelta } from '../types.js';
interface AnnotatedFormatterContext extends BaseFormatterContext {
    indentLevel?: number;
    indentPad?: string;
    indent: (levels?: number) => void;
    row: (json: string, htmlNote?: string) => void;
}
declare class AnnotatedFormatter extends BaseFormatter<AnnotatedFormatterContext> {
    constructor();
    prepareContext(context: Partial<AnnotatedFormatterContext>): void;
    typeFormattterErrorFormatter(context: AnnotatedFormatterContext, err: unknown): void;
    formatTextDiffString(context: AnnotatedFormatterContext, value: string): void;
    rootBegin(context: AnnotatedFormatterContext, type: DeltaType, nodeType: NodeType): void;
    rootEnd(context: AnnotatedFormatterContext, type: DeltaType): void;
    nodeBegin(context: AnnotatedFormatterContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType): void;
    nodeEnd(context: AnnotatedFormatterContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType, isLast: boolean): void;
    format_unchanged(): void;
    format_movedestination(): void;
    format_node(context: AnnotatedFormatterContext, delta: ObjectDelta | ArrayDelta, left: unknown): void;
    format_added(context: AnnotatedFormatterContext, delta: AddedDelta, left: unknown, key: string | undefined, leftKey: string | number | undefined): void;
    format_modified(context: AnnotatedFormatterContext, delta: ModifiedDelta, left: unknown, key: string | undefined, leftKey: string | number | undefined): void;
    format_deleted(context: AnnotatedFormatterContext, delta: DeletedDelta, left: unknown, key: string | undefined, leftKey: string | number | undefined): void;
    format_moved(context: AnnotatedFormatterContext, delta: MovedDelta, left: unknown, key: string | undefined, leftKey: string | number | undefined): void;
    format_textdiff(context: AnnotatedFormatterContext, delta: TextDiffDelta, left: unknown, key: string | undefined, leftKey: string | number | undefined): void;
}
export default AnnotatedFormatter;
export declare function format(delta: Delta, left?: unknown): string | undefined;
