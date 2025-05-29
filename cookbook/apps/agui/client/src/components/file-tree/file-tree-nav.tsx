import React from "react";
import { ChevronRight, FolderOpen } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { relative } from "path";

interface FileTreeNavProps {
  path: string;
  rootPath: string; // The demo's root path
  onNavigate?: (path: string) => void;
}

export function FileTreeNav({ path, rootPath, onNavigate }: FileTreeNavProps) {
  const folderName = rootPath.split("/").pop();
  // console.log("FILE TREE NAV", path, rootPath);
  // // Get path relative to the demo's root
  // const relativePath = "/" + relative(rootPath, path);
  // const parts = relativePath.split("/").filter(Boolean);

  return (
    <div className="flex items-center gap-1 p-2 text-sm border-b overflow-x-auto">
      <Button
        variant="ghost"
        size="sm"
        className="h-6 px-2"
        onClick={() => onNavigate?.(rootPath)}
      >
        <FolderOpen className="h-4 w-4" />
      </Button>
      <Button
        variant="ghost"
        size="sm"
        className={cn("h-6 px-2 truncate", "font-medium text-foreground")}
      >
        {folderName}
      </Button>
    </div>
  );
}
