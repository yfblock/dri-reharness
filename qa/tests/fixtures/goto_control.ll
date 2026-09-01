; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/goto_control.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/goto_control.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @goto_control(ptr noundef %0, i32 noundef %1) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !20, metadata !DIExpression()), !dbg !23
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !21, metadata !DIExpression()), !dbg !23
  %3 = icmp eq i32 %1, 0, !dbg !24
  br i1 %3, label %4, label %6, !dbg !26

4:                                                ; preds = %2
  %5 = getelementptr inbounds i8, ptr %0, i64 16, !dbg !27
  call void @llvm.dbg.value(metadata i32 1, metadata !28, metadata !DIExpression()), !dbg !37
  call void @llvm.dbg.value(metadata ptr %5, metadata !36, metadata !DIExpression()), !dbg !37
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 1, ptr nonnull elementtype(i32) %5) #3, !dbg !39, !srcloc !40
  br label %6, !dbg !41

6:                                                ; preds = %2, %4
  call void @llvm.dbg.label(metadata !22), !dbg !42
  %7 = getelementptr inbounds i8, ptr %0, i64 20, !dbg !43
  call void @llvm.dbg.value(metadata i32 2, metadata !28, metadata !DIExpression()), !dbg !44
  call void @llvm.dbg.value(metadata ptr %7, metadata !36, metadata !DIExpression()), !dbg !44
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 2, ptr nonnull elementtype(i32) %7) #3, !dbg !46, !srcloc !40
  ret void, !dbg !47
}

; Function Attrs: mustprogress nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.label(metadata) #1

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #2

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { mustprogress nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #2 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/goto_control.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "ad0fd994a92fa944a8ad8df9a1e46803")
!2 = !{!3}
!3 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !4, size: 64)
!4 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !5)
!5 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!6 = !{i32 7, !"Dwarf Version", i32 5}
!7 = !{i32 2, !"Debug Info Version", i32 3}
!8 = !{i32 1, !"wchar_size", i32 4}
!9 = !{i32 8, !"PIC Level", i32 2}
!10 = !{i32 7, !"PIE Level", i32 2}
!11 = !{i32 7, !"uwtable", i32 2}
!12 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!13 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!14 = distinct !DISubprogram(name: "goto_control", scope: !15, file: !15, line: 6, type: !16, scopeLine: 7, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !19)
!15 = !DIFile(filename: "qa/tests/fixtures/goto_control.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "ad0fd994a92fa944a8ad8df9a1e46803")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18, !5}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !{!20, !21, !22}
!20 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 6, type: !18)
!21 = !DILocalVariable(name: "skip", arg: 2, scope: !14, file: !15, line: 6, type: !5)
!22 = !DILabel(scope: !14, name: "out", file: !15, line: 12)
!23 = !DILocation(line: 0, scope: !14)
!24 = !DILocation(line: 8, column: 6, scope: !25)
!25 = distinct !DILexicalBlock(scope: !14, file: !15, line: 8, column: 6)
!26 = !DILocation(line: 8, column: 6, scope: !14)
!27 = !DILocation(line: 11, column: 17, scope: !14)
!28 = !DILocalVariable(name: "val", arg: 1, scope: !29, file: !30, line: 67, type: !5)
!29 = distinct !DISubprogram(name: "writel", scope: !30, file: !30, line: 67, type: !31, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !35)
!30 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!31 = !DISubroutineType(types: !32)
!32 = !{null, !5, !33}
!33 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !34, size: 64)
!34 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!35 = !{!28, !36}
!36 = !DILocalVariable(name: "addr", arg: 2, scope: !29, file: !30, line: 67, type: !33)
!37 = !DILocation(line: 0, scope: !29, inlinedAt: !38)
!38 = distinct !DILocation(line: 11, column: 2, scope: !14)
!39 = !DILocation(line: 67, column: 1, scope: !29, inlinedAt: !38)
!40 = !{i64 2149613689}
!41 = !DILocation(line: 11, column: 2, scope: !14)
!42 = !DILocation(line: 12, column: 1, scope: !14)
!43 = !DILocation(line: 13, column: 17, scope: !14)
!44 = !DILocation(line: 0, scope: !29, inlinedAt: !45)
!45 = distinct !DILocation(line: 13, column: 2, scope: !14)
!46 = !DILocation(line: 67, column: 1, scope: !29, inlinedAt: !45)
!47 = !DILocation(line: 14, column: 1, scope: !14)
