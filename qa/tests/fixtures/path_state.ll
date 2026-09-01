; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/path_state.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/path_state.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @path_state(ptr noundef %0, i32 noundef %1) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !20, metadata !DIExpression()), !dbg !27
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !21, metadata !DIExpression()), !dbg !27
  tail call void @llvm.dbg.value(metadata i32 1, metadata !22, metadata !DIExpression()), !dbg !27
  %3 = icmp eq i32 %1, 0, !dbg !28
  %4 = select i1 %3, i32 1, i32 2, !dbg !30
  tail call void @llvm.dbg.value(metadata i32 %4, metadata !22, metadata !DIExpression()), !dbg !27
  %5 = getelementptr inbounds i8, ptr %0, i64 32, !dbg !31
  call void @llvm.dbg.value(metadata i32 %4, metadata !32, metadata !DIExpression()), !dbg !41
  call void @llvm.dbg.value(metadata ptr %5, metadata !40, metadata !DIExpression()), !dbg !41
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 %4, ptr nonnull elementtype(i32) %5) #2, !dbg !43, !srcloc !44
  ret void, !dbg !45
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
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/path_state.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "bdf7557d25fd50777c47cc422727b277")
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
!14 = distinct !DISubprogram(name: "path_state", scope: !15, file: !15, line: 5, type: !16, scopeLine: 6, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !19)
!15 = !DIFile(filename: "qa/tests/fixtures/path_state.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "bdf7557d25fd50777c47cc422727b277")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18, !5}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !{!20, !21, !22}
!20 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 5, type: !18)
!21 = !DILocalVariable(name: "select", arg: 2, scope: !14, file: !15, line: 5, type: !5)
!22 = !DILocalVariable(name: "value", scope: !14, file: !15, line: 7, type: !23)
!23 = !DIDerivedType(tag: DW_TAG_typedef, name: "u32", file: !24, line: 21, baseType: !25)
!24 = !DIFile(filename: "vendor/linux/include/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "12ca7bdb629352cc4c9a492f86b435a7")
!25 = !DIDerivedType(tag: DW_TAG_typedef, name: "__u32", file: !26, line: 27, baseType: !5)
!26 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f4d0ec5bcdd84e825a78a7add39d54dd")
!27 = !DILocation(line: 0, scope: !14)
!28 = !DILocation(line: 9, column: 6, scope: !29)
!29 = distinct !DILexicalBlock(scope: !14, file: !15, line: 9, column: 6)
!30 = !DILocation(line: 9, column: 6, scope: !14)
!31 = !DILocation(line: 11, column: 21, scope: !14)
!32 = !DILocalVariable(name: "val", arg: 1, scope: !33, file: !34, line: 67, type: !5)
!33 = distinct !DISubprogram(name: "writel", scope: !34, file: !34, line: 67, type: !35, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !39)
!34 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!35 = !DISubroutineType(types: !36)
!36 = !{null, !5, !37}
!37 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !38, size: 64)
!38 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!39 = !{!32, !40}
!40 = !DILocalVariable(name: "addr", arg: 2, scope: !33, file: !34, line: 67, type: !37)
!41 = !DILocation(line: 0, scope: !33, inlinedAt: !42)
!42 = distinct !DILocation(line: 11, column: 2, scope: !14)
!43 = !DILocation(line: 67, column: 1, scope: !33, inlinedAt: !42)
!44 = !{i64 2149613648}
!45 = !DILocation(line: 12, column: 1, scope: !14)
