package com.nju.fixer;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.List;

public class PatchApplier {

    public static void applyPatch(String targetFilePath, int buggyLineNumber, String patchContent) throws IOException {
        Path targetPath = Paths.get(targetFilePath);
        List<String> lines = Files.readAllLines(targetPath);

        if (buggyLineNumber > 0 && buggyLineNumber <= lines.size()) {
            lines.set(buggyLineNumber - 1, patchContent); // Adjust for 0-based index
        } else {
            throw new IllegalArgumentException("Buggy line number " + buggyLineNumber + " is out of bounds for file " + targetFilePath);
        }

        Files.write(targetPath, lines);
    }

    public static void revertPatch(String targetFilePath, List<String> originalContent) throws IOException {
        Path targetPath = Paths.get(targetFilePath);
        Files.write(targetPath, originalContent);
    }
}
