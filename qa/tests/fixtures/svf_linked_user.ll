; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/svf_linked_user.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/svf_linked_user.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @svf_linked_alias_use() local_unnamed_addr #0 !dbg !14 {
  %1 = tail call ptr @svf_linked_map_hw() #3, !dbg !21
  tail call void @llvm.dbg.value(metadata ptr %1, metadata !19, metadata !DIExpression()), !dbg !22
  %2 = getelementptr inbounds i8, ptr %1, i64 36, !dbg !23
  call void @llvm.dbg.value(metadata i32 1, metadata !24, metadata !DIExpression()), !dbg !33
  call void @llvm.dbg.value(metadata ptr %2, metadata !32, metadata !DIExpression()), !dbg !33
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 1, ptr nonnull elementtype(i32) %2) #3, !dbg !35, !srcloc !36
  ret void, !dbg !37
}

declare !dbg !38 ptr @svf_linked_map_hw() local_unnamed_addr #1

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #2

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #2 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #3 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/svf_linked_user.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "9f5159058b123754007cebf5f3d9b940")
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
!14 = distinct !DISubprogram(name: "svf_linked_alias_use", scope: !15, file: !15, line: 5, type: !16, scopeLine: 6, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !18)
!15 = !DIFile(filename: "qa/tests/fixtures/svf_linked_user.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "9f5159058b123754007cebf5f3d9b940")
!16 = !DISubroutineType(types: !17)
!17 = !{null}
!18 = !{!19}
!19 = !DILocalVariable(name: "linked_alias", scope: !14, file: !15, line: 7, type: !20)
!20 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!21 = !DILocation(line: 7, column: 31, scope: !14)
!22 = !DILocation(line: 0, scope: !14)
!23 = !DILocation(line: 9, column: 25, scope: !14)
!24 = !DILocalVariable(name: "val", arg: 1, scope: !25, file: !26, line: 67, type: !5)
!25 = distinct !DISubprogram(name: "writel", scope: !26, file: !26, line: 67, type: !27, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !31)
!26 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!27 = !DISubroutineType(types: !28)
!28 = !{null, !5, !29}
!29 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !30, size: 64)
!30 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!31 = !{!24, !32}
!32 = !DILocalVariable(name: "addr", arg: 2, scope: !25, file: !26, line: 67, type: !29)
!33 = !DILocation(line: 0, scope: !25, inlinedAt: !34)
!34 = distinct !DILocation(line: 9, column: 2, scope: !14)
!35 = !DILocation(line: 67, column: 1, scope: !25, inlinedAt: !34)
!36 = !{i64 2149613664}
!37 = !DILocation(line: 10, column: 1, scope: !14)
!38 = !DISubprogram(name: "svf_linked_map_hw", scope: !15, file: !15, line: 3, type: !39, flags: DIFlagPrototyped, spFlags: DISPFlagOptimized)
!39 = !DISubroutineType(types: !40)
!40 = !{!20}
