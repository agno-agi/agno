import BaseFormatter from './base.js';
import type { BaseFormatterContext } from './base.js';
import type { AddedDelta, ArrayDelta, Delta, ModifiedDelta, MovedDelta, ObjectDelta } from '../types.js';
export interface AddOp {
    op: 'add';
    path: string;
    value: unknown;
}
export interface RemoveOp {
    op: 'remove';
    path: string;
}
export interface ReplaceOp {
    op: 'replace';
    path: string;
    value: unknown;
}
export interface MoveOp {
    op: 'move';
    from: string;
    path: string;
}
export type Op = AddOp | RemoveOp | ReplaceOp | MoveOp;
interface JSONFormatterContext extends BaseFormatterContext {
    result: Op[];
    path: (string | number)[];
    pushCurrentOp: (obj: {
        op: 'add';
        value: unknown;
    } | {
        op: 'remove';
    } | {
        op: 'replace';
        value: unknown;
    }) => void;
    pushMoveOp: (to: number) => void;
    currentPath: () => string;
    toPath: (to: number) => string;
}
declare class JSONFormatter extends BaseFormatter<JSONFormatterContext, Op[]> {
    constructor();
    prepareContext(context: Partial<JSONFormatterContext>): void;
    typeFormattterErrorFormatter(context: JSONFormatterContext, err: unknown): void;
    rootBegin(): void;
    rootEnd(): void;
    nodeBegin({ path }: JSONFormatterContext, key: string, leftKey: string | number): void;
    nodeEnd({ path }: JSONFormatterContext): void;
    format_unchanged(): void;
    format_movedestination(): void;
    format_node(context: JSONFormatterContext, delta: ObjectDelta | ArrayDelta, left: unknown): void;
    format_added(context: JSONFormatterContext, delta: AddedDelta): void;
    format_modified(context: JSONFormatterContext, delta: ModifiedDelta): void;
    format_deleted(context: JSONFormatterContext): void;
    format_moved(context: JSONFormatterContext, delta: MovedDelta): void;
    format_textdiff(): void;
    format(delta: Delta, left?: unknown): Op[];
}
export default JSONFormatter;
export declare const partitionOps: (arr: Op[], fns: ((op: Op) => boolean)[]) => Op[][];
export declare const format: (delta: Delta, left?: unknown) => Op[];
export declare const log: (delta: Delta, left?: unknown) => void;
