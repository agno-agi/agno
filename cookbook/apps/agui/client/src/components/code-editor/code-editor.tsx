import React from "react";
import Editor from "@monaco-editor/react";
import { DemoFile } from "@/types/demo";
import { useTheme } from "next-themes";
interface CodeEditorProps {
  file?: DemoFile;
  onFileChange?: (fileName: string, content: string) => void;
}

export function CodeEditor({ file, onFileChange }: CodeEditorProps) {
  const handleEditorChange = (value: string | undefined) => {
    if (value && onFileChange) {
      onFileChange(file!.name, value);
    }
  };

  const theme = useTheme();

  return file ? (
    <div className="h-full flex flex-col">
      <Editor
        height="100%"
        language={file.language}
        value={file.content}
        onChange={handleEditorChange}
        options={{
          minimap: { enabled: false },
          fontSize: 16,
          lineNumbers: "on",
          readOnly: true,
          wordWrap: "on",
          stickyScroll: {
            enabled: false,
          },
        }}
        theme={theme.theme === "dark" ? "vs-dark" : "vs-light"}
      />
    </div>
  ) : (
    <div className="p-6 text-center text-muted-foreground">
      Select a file from the file tree to view its code
    </div>
  );
}
