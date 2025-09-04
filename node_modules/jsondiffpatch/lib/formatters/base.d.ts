import type { AddedDelta, ArrayDelta, DeletedDelta, Delta, ModifiedDelta, MovedDelta, ObjectDelta, TextDiffDelta } from '../types.js';
export interface BaseFormatterContext {
    buffer: string[];
    out: (...args: string[]) => void;
}
export type DeltaType = 'movedestination' | 'unchanged' | 'added' | 'modified' | 'deleted' | 'textdiff' | 'moved' | 'node' | 'unknown';
export type NodeType = 'array' | 'object' | '';
interface DeltaTypeMap {
    movedestination: undefined;
    unchanged: undefined;
    added: AddedDelta;
    modified: ModifiedDelta;
    deleted: DeletedDelta;
    textdiff: TextDiffDelta;
    moved: MovedDelta;
    node: ObjectDelta | ArrayDelta;
}
interface MoveDestination {
    key: `_${number}`;
    value: unknown;
}
interface LineOutputPiece {
    type: 'context' | 'added' | 'deleted';
    text: string;
}
interface LineOutputLocation {
    line: string;
    chr: string;
}
interface LineOutput {
    pieces: LineOutputPiece[];
    location: LineOutputLocation;
}
declare abstract class BaseFormatter<TContext extends BaseFormatterContext, TFormatted = string | undefined> {
    includeMoveDestinations?: boolean;
    format(delta: Delta, left?: unknown): TFormatted;
    prepareContext(context: Partial<TContext>): void;
    typeFormattterNotFound(context: TContext, deltaType: 'unknown'): never;
    typeFormattterErrorFormatter(context: TContext, err: unknown, delta: Delta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    finalize({ buffer }: TContext): string | undefined;
    recurse<TDeltaType extends keyof DeltaTypeMap>(context: TContext, delta: DeltaTypeMap[TDeltaType], left: unknown, key?: string, leftKey?: string | number, movedFrom?: MoveDestination | undefined, isLast?: boolean): undefined;
    formatDeltaChildren(context: TContext, delta: ObjectDelta | ArrayDelta, left: unknown): void;
    forEachDeltaKey(delta: ObjectDelta | ArrayDelta, left: unknown, fn: (key: string, leftKey: string | number, moveDestination: MoveDestination | undefined, isLast: boolean) => void): void;
    getDeltaType(delta: Delta, movedFrom?: MoveDestination | undefined): "unknown" | "movedestination" | "unchanged" | "added" | "modified" | "deleted" | "textdiff" | "moved" | "node";
    parseTextDiff(value: string): LineOutput[];
    abstract rootBegin(context: TContext, type: DeltaType, nodeType: NodeType): void;
    abstract rootEnd(context: TContext, type: DeltaType, nodeType: NodeType): void;
    abstract nodeBegin(context: TContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType, isLast: boolean): void;
    abstract nodeEnd(context: TContext, key: string, leftKey: string | number, type: DeltaType, nodeType: NodeType, isLast: boolean): void;
    abstract format_unchanged(context: TContext, delta: undefined, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_movedestination(context: TContext, delta: undefined, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_node(context: TContext, delta: ObjectDelta | ArrayDelta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_added(context: TContext, delta: AddedDelta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_modified(context: TContext, delta: ModifiedDelta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_deleted(context: TContext, delta: DeletedDelta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_moved(context: TContext, delta: MovedDelta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
    abstract format_textdiff(context: TContext, delta: TextDiffDelta, leftValue: unknown, key: string | undefined, leftKey: string | number | undefined, movedFrom: MoveDestination | undefined): void;
}
export default BaseFormatter;
