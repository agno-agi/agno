import { useState, useCallback } from "react";
import { FileEntry } from "@/components/file-tree/file-tree";
import { join } from "path";
import config from "@/config";

export function useFs(initialPath: string) {
  const [currentPath, setCurrentPath] = useState(initialPath);
  const [files, setFiles] = useState<FileEntry[]>([]);
  const [selectedFilePath, setSelectedFilePath] = useState<string>();
  const [fileContent, setFileContent] = useState<string>();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string>();

  const listFiles = useCallback(async (path: string) => {
    const id = path.split("/").pop();
    const demo = config.find((d) => d.id === id);
    if (demo) {
      const fileEntries: FileEntry[] = demo.files.map((file) => ({
        name: file.name,
        path: id + "/" + file.path,
        content: file.content,
        type: "file",
      }));
      setFiles(fileEntries);
    } else {
      setFiles([]);
    }
  }, []);

  const readFile = useCallback(
    async (relativePath: string) => {
      const [id, ...rest] = relativePath.split("/");
      const fileName = rest.join("/");

      const demo = config.find((d) => d.id === id);
      if (!demo) {
        setFileContent("");
        setSelectedFilePath("");
        return;
      }

      const file = demo.files.find((f) => f.path === fileName);
      if (!file) {
        setFileContent("");
        setSelectedFilePath("");
        return;
      }

      setFileContent(file.content);
      setSelectedFilePath(file.path);
    },
    []
  );

  const handleFileSelect = useCallback(
    (path: string) => {
      readFile(path);
    },
    [readFile]
  );

  const handleNavigate = useCallback(
    (path: string) => {
      listFiles(path);
    },
    [listFiles]
  );

  return {
    currentPath,
    files,
    selectedFilePath,
    fileContent,
    loading,
    error,
    handleFileSelect,
    handleNavigate,
  };
}
