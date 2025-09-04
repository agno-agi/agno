import { type Hook } from "@hono/zod-validator";
import type { Env, Input, MiddlewareHandler, ValidationTargets } from "hono";
import type { ZodSchema, z } from "zod";
import type { HasUndefined, ResolverResult } from "./types.js";
/**
 * Generate a resolver for a Zod schema
 * @param schema Zod schema
 * @returns Resolver result
 */
export declare function resolver<T extends ZodSchema>(schema: T): ResolverResult;
/**
 * Create a validator middleware
 * @param target Target for validation
 * @param schema Zod schema
 * @param hook Hook for validation
 * @returns Middleware handler
 */
export declare function validator<T extends ZodSchema, Target extends keyof ValidationTargets, E extends Env, P extends string, In = z.input<T>, Out = z.output<T>, I extends Input = {
    in: HasUndefined<In> extends true ? {
        [K in Target]?: In extends ValidationTargets[K] ? In : {
            [K2 in keyof In]?: ValidationTargets[K][K2];
        };
    } : {
        [K in Target]: In extends ValidationTargets[K] ? In : {
            [K2 in keyof In]: ValidationTargets[K][K2];
        };
    };
    out: {
        [K in Target]: Out;
    };
}, V extends I = I>(target: Target, schema: T, hook?: Hook<z.infer<T>, E, P, Target>): MiddlewareHandler<E, P, V>;
