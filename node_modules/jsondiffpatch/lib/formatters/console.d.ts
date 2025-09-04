import type { ChalkInstance } from 'chalk';
import BaseFormatter from './base.js';
import type { BaseFormatterContext, DeltaType, NodeType } from './base.js';
import type { AddedDelta, ArrayDelta, DeletedDelta, Delta, ModifiedDelta, MovedDelta, ObjectDelta, TextDiffDelta } from '../types.js';
interface ConsoleFormatterContext extends BaseFormatterContext {
    indentLevel?: number;
    indentPad?: string;
    outLine: () => void;
    indent: (levels?: number) => void;
    color?: (ChalkInstance | undefined)[];
    pushColor: (color: ChalkInstance | undefined) => void;
    popColor: () => void;
}
declare class ConsoleFormatter extends BaseFormatter<ConsoleFormatterContext> {
    constructor();
    prepareContext(context: Partial<ConsoleFormatterContext>): void;
    typeFormattterErrorFormatter(context: ConsoleFormatterContext, err: unknown): void;
    formatValue(context: ConsoleFormatterContext, value: unknown): void;
    formatTextDiffString(context: ConsoleFormatterContext, value: string): void;
    rootBegin(context: ConsoleFormatterContext, type: DeltaType, nodeType: NodeType): void;
    rootEnd(context: ConsoleFormatterContext, type: DeltaType, nodeType: NodeType): void;
    nodeBegin(context: ConsoleFormatterContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType): void;
    nodeEnd(context: ConsoleFormatterContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType, isLast: boolean): void;
    format_unchanged(context: ConsoleFormatterContext, delta: undefined, left: unknown): void;
    format_movedestination(context: ConsoleFormatterContext, delta: undefined, left: unknown): void;
    format_node(context: ConsoleFormatterContext, delta: ObjectDelta | ArrayDelta, left: unknown): void;
    format_added(context: ConsoleFormatterContext, delta: AddedDelta): void;
    format_modified(context: ConsoleFormatterContext, delta: ModifiedDelta): void;
    format_deleted(context: ConsoleFormatterContext, delta: DeletedDelta): void;
    format_moved(context: ConsoleFormatterContext, delta: MovedDelta): void;
    format_textdiff(context: ConsoleFormatterContext, delta: TextDiffDelta): void;
}
export default ConsoleFormatter;
export declare const format: (delta: Delta, left?: unknown) => string | undefined;
export declare function log(delta: Delta, left?: unknown): void;
