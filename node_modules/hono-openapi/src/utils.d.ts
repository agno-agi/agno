import type { ValidationTargets } from "hono";
import type { OpenAPIV3 } from "openapi-types";
import type { ResolverResult } from "./types.js";
/**
 * The unique symbol for the middlewares, which makes it easier to identify them. Not meant to be used directly, unless you're creating a custom middleware.
 */
export declare const uniqueSymbol: unique symbol;
/**
 * Generate OpenAPI docs for a validator middleware. Not meant to be used directly, unless you're creating a custom middleware.
 */
export declare function generateValidatorDocs<Target extends keyof ValidationTargets>(target: Target, _result: ReturnType<ResolverResult["builder"]>): Promise<{
    docs: Pick<{
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
    }, "parameters" | "requestBody">;
    components: {
        [key: string]: OpenAPIV3.ReferenceObject | OpenAPIV3.SchemaObject;
    } | undefined;
}>;
