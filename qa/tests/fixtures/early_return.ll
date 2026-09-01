; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/early_return.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/early_return.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @early_return(ptr noundef %0, i32 noundef %1) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !20, metadata !DIExpression()), !dbg !22
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !21, metadata !DIExpression()), !dbg !22
  %3 = icmp eq i32 %1, 0, !dbg !23
  br i1 %3, label %6, label %4, !dbg !25

4:                                                ; preds = %2
  %5 = getelementptr inbounds i8, ptr %0, i64 32, !dbg !26
  call void @llvm.dbg.value(metadata i32 1, metadata !27, metadata !DIExpression()), !dbg !36
  call void @llvm.dbg.value(metadata ptr %5, metadata !35, metadata !DIExpression()), !dbg !36
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 1, ptr nonnull elementtype(i32) %5) #2, !dbg !38, !srcloc !39
  br label %6, !dbg !40

6:                                                ; preds = %2, %4
  ret void, !dbg !40
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #2 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/early_return.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "01e48cb55706d18429deea7f4d4509db")
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
!14 = distinct !DISubprogram(name: "early_return", scope: !15, file: !15, line: 5, type: !16, scopeLine: 6, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !19)
!15 = !DIFile(filename: "qa/tests/fixtures/early_return.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "01e48cb55706d18429deea7f4d4509db")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18, !5}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !{!20, !21}
!20 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 5, type: !18)
!21 = !DILocalVariable(name: "enabled", arg: 2, scope: !14, file: !15, line: 5, type: !5)
!22 = !DILocation(line: 0, scope: !14)
!23 = !DILocation(line: 7, column: 7, scope: !24)
!24 = distinct !DILexicalBlock(scope: !14, file: !15, line: 7, column: 6)
!25 = !DILocation(line: 7, column: 6, scope: !14)
!26 = !DILocation(line: 10, column: 17, scope: !14)
!27 = !DILocalVariable(name: "val", arg: 1, scope: !28, file: !29, line: 67, type: !5)
!28 = distinct !DISubprogram(name: "writel", scope: !29, file: !29, line: 67, type: !30, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !34)
!29 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!30 = !DISubroutineType(types: !31)
!31 = !{null, !5, !32}
!32 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !33, size: 64)
!33 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!34 = !{!27, !35}
!35 = !DILocalVariable(name: "addr", arg: 2, scope: !28, file: !29, line: 67, type: !32)
!36 = !DILocation(line: 0, scope: !28, inlinedAt: !37)
!37 = distinct !DILocation(line: 10, column: 2, scope: !14)
!38 = !DILocation(line: 67, column: 1, scope: !28, inlinedAt: !37)
!39 = !{i64 2149613634}
!40 = !DILocation(line: 11, column: 1, scope: !14)
