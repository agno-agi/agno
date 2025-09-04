import { type Hook } from "@hono/arktype-validator";
import type { Type } from "arktype";
import type { Env, MiddlewareHandler, ValidationTargets } from "hono";
import type { HasUndefined, ResolverResult } from "./types.js";
/**
 * Generate a resolver for an Arktype schema
 * @param schema Arktype schema
 * @returns Resolver result
 */
export declare function resolver<T extends Type>(schema: T): ResolverResult;
/**
 * Create a validator middleware
 * @param target Target for validation
 * @param schema Arktype schema
 * @param hook Hook for validation
 * @returns Middleware handler
 */
export declare function validator<T extends Type, Target extends keyof ValidationTargets, E extends Env, P extends string, I = T["inferIn"], O = T["infer"], V extends {
    in: HasUndefined<I> extends true ? {
        [K in Target]?: I;
    } : {
        [K in Target]: I;
    };
    out: {
        [K in Target]: O;
    };
} = {
    in: HasUndefined<I> extends true ? {
        [K in Target]?: I;
    } : {
        [K in Target]: I;
    };
    out: {
        [K in Target]: O;
    };
}>(target: Target, schema: T, hook?: Hook<T["infer"], E, P>): MiddlewareHandler<E, P, V>;
