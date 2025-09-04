import type { Context, Env, Hono, Input, Schema } from "hono";
import type { BlankEnv, BlankInput, BlankSchema, MiddlewareHandler } from "hono/types";
import type { OpenAPIV3 } from "openapi-types";
import type { OpenAPIRouteHandlerConfig, OpenApiSpecsOptions } from "./types.js";
/**
 * Route handler for OpenAPI specs
 * @param hono Instance of Hono
 * @param options Options for generating OpenAPI specs
 * @returns Middleware handler for OpenAPI specs
 */
export declare function openAPISpecs<E extends Env = BlankEnv, P extends string = string, I extends Input = BlankInput, S extends Schema = BlankSchema>(hono: Hono<E, S, P>, options?: OpenApiSpecsOptions): MiddlewareHandler<E, P, I>;
/**
 * Generate OpenAPI specs for the given Hono instance
 * @param hono Instance of Hono
 * @param options Options for generating OpenAPI specs
 * @param config Configuration for OpenAPI route handler
 * @param Context Route context for hiding routes
 * @returns OpenAPI specs
 */
export declare function generateSpecs<E extends Env = BlankEnv, P extends string = string, I extends Input = BlankInput, S extends Schema = BlankSchema>(hono: Hono<E, S, P>, options?: OpenApiSpecsOptions, config?: OpenAPIRouteHandlerConfig, c?: Context<E, P, I>): Promise<{
    tags: OpenAPIV3.TagObject[] | undefined;
    info: {
        title: string;
        description: string;
        termsOfService?: string;
        contact?: OpenAPIV3.ContactObject;
        license?: OpenAPIV3.LicenseObject;
        version: string;
    };
    paths: {
        [x: string]: ({
            $ref?: string;
            summary?: string;
            description?: string;
            servers?: OpenAPIV3.ServerObject[];
            parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
        } & {
            get?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            put?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            post?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            delete?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            options?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            head?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            patch?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
            trace?: {
                tags?: string[];
                summary?: string;
                description?: string;
                externalDocs?: OpenAPIV3.ExternalDocumentationObject;
                operationId?: string;
                parameters?: (OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject)[];
                requestBody?: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
                responses: OpenAPIV3.ResponsesObject;
                callbacks?: {
                    [callback: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
                };
                deprecated?: boolean;
                security?: OpenAPIV3.SecurityRequirementObject[];
                servers?: OpenAPIV3.ServerObject[];
            } | undefined;
        }) | undefined;
    };
    components: {
        schemas: {
            [x: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.SchemaObject;
        };
        responses?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.ResponseObject;
        };
        parameters?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.ParameterObject;
        };
        examples?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.ExampleObject;
        };
        requestBodies?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.RequestBodyObject;
        };
        headers?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.HeaderObject;
        };
        securitySchemes?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.SecuritySchemeObject;
        };
        links?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.LinkObject;
        };
        callbacks?: {
            [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.CallbackObject;
        };
    };
    openapi: string;
    servers?: OpenAPIV3.ServerObject[] | undefined;
    security?: OpenAPIV3.SecurityRequirementObject[] | undefined;
    externalDocs?: OpenAPIV3.ExternalDocumentationObject | undefined;
}>;
