import { type Hook } from "@hono/valibot-validator";
import { type ConversionConfig } from "@valibot/to-json-schema";
import type { Env, Input as HonoInput, MiddlewareHandler, ValidationTargets } from "hono";
import { type BaseIssue, type BaseSchema, type GenericSchema, type GenericSchemaAsync, type InferInput, type InferOutput } from "valibot";
import type { HasUndefined, ResolverResult } from "./types.js";
/**
 * Generate a resolver for a Valibot schema
 * @param schema Valibot schema
 * @returns Resolver result
 */
export declare function resolver<T extends BaseSchema<unknown, unknown, BaseIssue<unknown>>>(schema: T, config?: ConversionConfig): ResolverResult;
/**
 * Create a validator middleware
 * @param target Target for validation
 * @param schema Valibot schema
 * @param hook Hook for validation
 * @returns Middleware handler
 */
export declare function validator<T extends GenericSchema | GenericSchemaAsync, Target extends keyof ValidationTargets, E extends Env, P extends string, In = InferInput<T>, Out = InferOutput<T>, I extends HonoInput = {
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
}, V extends I = I>(target: Target, schema: T, hook?: Hook<T, E, P>): MiddlewareHandler<E, P, V>;
