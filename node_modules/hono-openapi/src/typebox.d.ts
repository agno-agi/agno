import { type Hook } from "@hono/typebox-validator";
import type { Static, TSchema } from "@sinclair/typebox";
import type { Env, MiddlewareHandler, ValidationTargets } from "hono";
import type { ResolverResult } from "./types.js";
/**
 * Generate a resolver for a TypeBox schema
 * @param schema TypeBox schema
 * @returns Resolver result
 */
export declare function resolver<T extends TSchema>(schema: T): ResolverResult;
/**
 * Create a validator middleware
 * @param target Target for validation
 * @param schema TypeBox schema
 * @param hook Hook for validation
 * @returns Middleware handler
 */
export declare function validator<T extends TSchema, Target extends keyof ValidationTargets, E extends Env, P extends string, V extends {
    in: {
        [K in Target]: Static<T>;
    };
    out: {
        [K in Target]: Static<T>;
    };
}>(target: Target, schema: T, hook?: Hook<Static<T>, E, P>): MiddlewareHandler<E, P, V>;
