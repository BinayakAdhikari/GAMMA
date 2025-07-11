package com.nju.fixer;

import org.junit.Test;
import static org.junit.Assert.*;

import javax.tools.JavaCompiler;
import javax.tools.ToolProvider;
import java.io.*;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.Paths;
import java.util.ArrayList;
import java.util.List;
import java.util.stream.Collectors;
import org.junit.runner.JUnitCore;
import org.junit.runner.Result;
import org.junit.runner.notification.Failure;
import java.io.FileWriter;
import java.io.BufferedWriter;

public class PatchValidationTest {

    private static final String PROJECT_ROOT = new File(System.getProperty("user.dir")).getParent() + File.separator;
    private static final String QUIXBUGS_DIR = PROJECT_ROOT + "patchGeneration" + File.separator + "QuixBugs" + File.separator;
    private static final String JAVA_PROGRAMS_DIR = QUIXBUGS_DIR + "java_programs" + File.separator;
    private static final String JAVA_TESTCASES_DIR = QUIXBUGS_DIR + "java_testcases" + File.separator;
    private static final String META_FILE = PROJECT_ROOT + "patchGeneration" + File.separator + "quixbugs_meta.txt";
    private static final String UNIXCODER_PATCHES_DIR = PROJECT_ROOT + "patchGeneration" + File.separator + "unixcoder_patches" + File.separator;
    private static final String CODEBERT_PATCHES_DIR = PROJECT_ROOT + "patchGeneration" + File.separator + "codebert_patches" + File.separator;
    private static final String REPORT_CSV_PATH = PROJECT_ROOT + "gemini_output" + File.separator + "patch_validation_report.csv";

    private List<PatchResult> allPatchResults = new ArrayList<>();

    private static class PatchResult {
        String bugName;
        String model;
        String status;
        String patchContent;

        public PatchResult(String bugName, String model, String status, String patchContent) {
            this.bugName = bugName;
            this.model = model;
            this.status = status;
            this.patchContent = patchContent;
        }
    }

    @Test
    public void validatePatches() throws IOException {
        allPatchResults.clear();
        List<String> metaLines = Files.readAllLines(Paths.get(META_FILE));

        System.out.println("\n--- Validating UniXcoder Patches ---");
        validateModelPatches(UNIXCODER_PATCHES_DIR, "UniXcoder", metaLines);

        System.out.println("\n--- Validating CodeBERT Patches ---");
        validateModelPatches(CODEBERT_PATCHES_DIR, "CodeBERT", metaLines);

        writeCsvReport();
    }

    private void validateModelPatches(String patchesDir, String modelName, List<String> metaLines) throws IOException {
        JavaCompiler compiler = ToolProvider.getSystemJavaCompiler();
        if (compiler == null) {
            System.err.println("JDK not found. Please ensure you are running with a JDK (not just a JRE).");
            return;
        }

        int passedCount = 0;
        int failedCount = 0;
        List<String> patchedBugs = new ArrayList<>();

        for (int i = 0; i < metaLines.size(); i++) {
            String metaLine = metaLines.get(i);
            String[] parts = metaLine.split("\t");
            if (parts.length < 3) continue;

            String bugName = parts[0];
            int buggyLineNumber = Integer.parseInt(parts[1]);
            String originalProgramPath = JAVA_PROGRAMS_DIR + bugName + ".java";
            String testCasePath = PROJECT_ROOT + "fixer-demo" + File.separator + "src" + File.separator + "test" + File.separator + "java" + File.separator + "java_testcases" + File.separator + "junit" + File.separator + bugName.toUpperCase() + "_TEST.java";
            String nodePath = JAVA_PROGRAMS_DIR + "Node.java";

            Path patchFilePath = Paths.get(patchesDir + String.format("%03d", i + 1) + "_line" + buggyLineNumber + ".txt");
            if (!Files.exists(patchFilePath)) {
                System.out.println("Skipping " + bugName + ": Patch file not found at " + patchFilePath);
                allPatchResults.add(new PatchResult(bugName, modelName, "SKIPPED - Patch File Not Found", "N/A"));
                continue;
            }

            List<String> patchContents = Files.readAllLines(patchFilePath);
            if (patchContents.isEmpty()) {
                System.out.println("Skipping " + bugName + ": Patch file is empty.");
                allPatchResults.add(new PatchResult(bugName, modelName, "SKIPPED - Empty Patch File", "N/A"));
                continue;
            }

            // Iterate through all patches for this bug
            for (String patchContent : patchContents) {
                System.out.println("Validating " + bugName + " with patch: " + patchContent);

                List<String> originalFileContent = null; // Store original content
                try {
                    // Read original file content before patching
                    originalFileContent = Files.readAllLines(Paths.get(originalProgramPath));

                    // Apply patch directly to the original file
                    PatchApplier.applyPatch(originalProgramPath, buggyLineNumber, patchContent);

                    // Compile patched program and its test
                    String classpath = System.getProperty("java.class.path") + File.pathSeparator + JAVA_PROGRAMS_DIR + File.pathSeparator + JAVA_TESTCASES_DIR;
                    String[] compileArgs = {
                            "-d", "target/classes", // Compile to target/classes
                            "-cp", classpath,
                            originalProgramPath, // Use originalProgramPath directly
                            Paths.get(testCasePath).toString(),
                            Paths.get(nodePath).toString() // Include Node.java
                    };

                    int compilationResult = compiler.run(null, null, null, compileArgs);
                    boolean compilationSuccess = (compilationResult == 0);
                    if (!compilationSuccess) {
                        System.err.println("Compilation failed for " + bugName);
                        failedCount++;
                        allPatchResults.add(new PatchResult(bugName, modelName, "FAILED - Compilation Error", patchContent));
                        continue;
                    }

                    // Run the test using JUnitCore
                    JUnitCore junit = new JUnitCore();
                    Result result = junit.run(Class.forName("java_testcases.junit." + bugName.toUpperCase() + "_TEST"));

                    System.out.println("Test Output:");
                    for (Failure failure : result.getFailures()) {
                        System.out.println(failure.toString());
                    }

                    boolean testPassed = result.wasSuccessful();
                    if (testPassed) {
                        System.out.println("Patch for " + bugName + " PASSED.");
                        passedCount++;
                        if (!patchedBugs.contains(bugName)) {
                            patchedBugs.add(bugName);
                        }
                        allPatchResults.add(new PatchResult(bugName, modelName, "PASSED", patchContent));
                    } else {
                        System.err.println("Patch for " + bugName + " FAILED.");
                        failedCount++;
                        allPatchResults.add(new PatchResult(bugName, modelName, "FAILED - Test Failure", patchContent));
                    }

                } catch (Exception e) {
                    System.err.println("Error validating " + bugName + ": " + e.getMessage());
                    e.printStackTrace();
                    failedCount++;
                    allPatchResults.add(new PatchResult(bugName, modelName, "FAILED - Exception", patchContent));
                } finally {
                    // Revert the file to its original content
                    if (originalFileContent != null) {
                        PatchApplier.revertPatch(originalProgramPath, originalFileContent);
                    }
                }
            }
        }
        System.out.println(String.format("\n--- Summary for %s ---", modelName));
        System.out.println("Passed: " + passedCount);
        System.out.println("Failed: " + failedCount);
        System.out.println("Buggy snippets patched correctly: " + patchedBugs.size());
        System.out.println("-------------------------------------");
    }

    private void writeCsvReport() throws IOException {
        try (BufferedWriter writer = new BufferedWriter(new FileWriter(REPORT_CSV_PATH))) {
            writer.write("Bug Name,Model,Status,Patch Content\n");
            for (PatchResult result : allPatchResults) {
                if (result.status.equals("PASSED")) {
                    writer.write(String.format("%s,%s,%s,%s\n", result.bugName, result.model, result.status, result.patchContent.replace("\n", " ")));
                }
            }
        }
        System.out.println("\nReport generated at: " + REPORT_CSV_PATH);
    }
}