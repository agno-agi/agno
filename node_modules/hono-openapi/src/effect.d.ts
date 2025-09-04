import { Schema } from "effect";
import type { Env, Input as HonoInput, MiddlewareHandler, ValidationTargets } from "hono";
import type { HasUndefined, ResolverResult } from "./types.js";
/**
 * Generate a resolver for an Effect schema
 * @param schema Effect schema
 * @returns Resolver result
 */
export declare function resolver<Type, Context>(schema: Schema.Schema<Type, Context, never>): ResolverResult;
/**
 * Create a validator middleware
 * @param target Target for validation
 * @param schema Effect schema
 * @returns Middleware handler
 */
export declare function validator<Type, Context, Target extends keyof ValidationTargets, E extends Env, P extends string, In = Schema.Schema<Type, Context, never>["Encoded"], Out = Schema.Schema<Type, Context, never>["Type"], I extends HonoInput = {
    in: HasUndefined<In> extends true ? {
        [K in Target]?: K extends "json" ? In : HasUndefined<keyof ValidationTargets[K]> extends true ? {
            [K2 in keyof In]?: ValidationTargets[K][K2];
        } : {
            [K2 in keyof In]: ValidationTargets[K][K2];
        };
    } : {
        [K in Target]: K extends "json" ? In : HasUndefined<keyof ValidationTargets[K]> extends true ? {
            [K2 in keyof In]?: ValidationTargets[K][K2];
        } : {
            [K2 in keyof In]: ValidationTargets[K][K2];
        };
    };
    out: {
        [K in Target]: Out;
    };
}, V extends I = I>(target: Target, schema: Schema.Schema<Type, Context, never>): MiddlewareHandler<E, P, V>;
