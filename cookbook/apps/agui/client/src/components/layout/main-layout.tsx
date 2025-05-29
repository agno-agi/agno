"use client";

import React, { useState, useEffect, useCallback } from "react";
import { ViewerLayout } from "@/components/layout/viewer-layout";
import { Sidebar } from "@/components/sidebar/sidebar";
import { FileTree } from "@/components/file-tree/file-tree";
import { FileTreeNav } from "@/components/file-tree/file-tree-nav";
import { CodeEditor } from "@/components/code-editor/code-editor";
import { useFs } from "@/hooks/use-fs";
import { usePathname } from "next/navigation";
import config from "@/config";
import ReactMarkdown from "react-markdown";
import { MarkdownComponents } from "@/components/ui/markdown-components";
import { MDXContent } from "@/components/ui/mdx-components";
import { MDXRenderer, SafeComponent } from "@/utils/mdx-utils";

export function MainLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const [activeTab, setActiveTab] = useState<string>("preview");
  const [readmeContent, setReadmeContent] = useState<string | null>(null);
  const [compiledMDX, setCompiledMDX] = useState<string | null>(null);
  
  // Extract the current demo ID from the pathname
  const pathParts = pathname.split('/');
  const currentDemoId = pathParts[pathParts.length - 1];
  const currentDemo = config.find(d => d.id === currentDemoId);
  
  // Original path format for code and readme loading
  const demoPath = currentDemo ? `agent/demo/${currentDemo.id}` : "";
  
  const {
    currentPath,
    files,
    selectedFilePath,
    fileContent,
    error,
    handleFileSelect,
    handleNavigate,
  } = useFs(demoPath);
  
  // Load README content
  const loadReadmeContent = useCallback(async (demoId: string) => {
    if (!demoId) return;
    
    // Process MDX if the file exists
    try {
      const mdxResponse = await fetch("/api/mdx/process", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ demoId }),
      });

      if (mdxResponse.ok) {
        const { compiled, content } = await mdxResponse.json();
        setCompiledMDX(compiled);
        setReadmeContent(content);
      } else {
        setCompiledMDX(null);
        setReadmeContent(null);
      }
    } catch (mdxError) {
      console.error("Error processing MDX:", mdxError);
      setCompiledMDX(null);
    }
  }, []);

  // Load initial demo files when demo changes
  useEffect(() => {
    if (currentDemoId) {
      handleNavigate(demoPath);
      loadReadmeContent(currentDemoId);
    }
  }, [currentDemoId, demoPath, handleNavigate, loadReadmeContent]);

  // Find agent.py file when switching to code tab
  const handleTabChange = (value: string) => {
    setActiveTab(value);
    if (value === "code" && files) {
      // Look for agent.py file
      const agentFile = files.find(
        (file) => file.name === "agent.py" || file.path.endsWith("/agent.py")
      );

      if (agentFile) {
        handleFileSelect(agentFile.path);
      }
    }
  };

  return (
    <ViewerLayout showFileTree={false} showCodeEditor={false}>
      <div className="flex h-full w-full overflow-hidden">
        {/* Sidebar */}
        <Sidebar 
          activeTab={activeTab} 
          onTabChange={handleTabChange}
          readmeContent={readmeContent} 
        />
        
        {/* Content */}
        <div className="flex-1 overflow-auto">
          {activeTab === "preview" ? (
            <div className="h-full">
              {children}
            </div>
          ) : activeTab === "readme" && readmeContent ? (
            <div className="flex-1 p-6 overflow-auto bg-background">
              <div className="max-w-4xl mx-auto">
                <div className="prose max-w-none">
                  {compiledMDX ? (
                    <MDXContent>
                      <SafeComponent
                        component={() => (
                          <MDXRenderer
                            content={readmeContent}
                            demoId={currentDemoId}
                          />
                        )}
                        fallback={
                          <div className="p-4 border rounded bg-amber-50 dark:bg-amber-900/20 text-amber-700 dark:text-amber-300">
                            Could not render MDX content. Displaying markdown
                            instead.
                            <ReactMarkdown components={MarkdownComponents}>
                              {readmeContent || ""}
                            </ReactMarkdown>
                          </div>
                        }
                      />
                    </MDXContent>
                  ) : (
                    <ReactMarkdown components={MarkdownComponents}>
                      {readmeContent}
                    </ReactMarkdown>
                  )}
                </div>
              </div>
            </div>
          ) : activeTab === "code" ? (
            <div className="flex-1 flex h-full">
              <div className="w-72 border-r flex flex-col">
                <FileTreeNav
                  path={currentPath}
                  rootPath={demoPath}
                  onNavigate={handleNavigate}
                />
                <div className="flex-1 overflow-auto">
                  <FileTree
                    basePath={currentPath}
                    files={files}
                    selectedFile={selectedFilePath}
                    onFileSelect={handleFileSelect}
                  />
                </div>
                {error && (
                  <div className="p-2 text-sm text-red-500">{error}</div>
                )}
              </div>
              <div className="flex-1">
                {selectedFilePath && fileContent && (
                  <div className="h-full">
                    <CodeEditor
                      file={{
                        name: selectedFilePath?.split("/").pop() || "",
                        path: selectedFilePath || "",
                        content: fileContent,
                        language: selectedFilePath?.endsWith(".py")
                          ? "python"
                          : selectedFilePath?.endsWith(".ts") ||
                            selectedFilePath?.endsWith(".tsx")
                          ? "typescript"
                          : selectedFilePath?.endsWith(".js") ||
                            selectedFilePath?.endsWith(".jsx")
                          ? "javascript"
                          : selectedFilePath?.endsWith(".yaml")
                          ? "yaml"
                          : selectedFilePath?.endsWith(".toml")
                          ? "toml"
                          : "plaintext",
                      }}
                    />
                  </div>
                )}
              </div>
            </div>
          ) : (
            <div className="flex-1 flex items-center justify-center text-muted-foreground">
              Select a demo from the list to get started
            </div>
          )}
        </div>
      </div>
    </ViewerLayout>
  );
} 