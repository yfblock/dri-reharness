; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/infeasible_path.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/infeasible_path.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: mustprogress nofree norecurse nosync nounwind willreturn memory(none) uwtable
define dso_local void @infeasible_path(ptr nocapture noundef readnone %0, i32 noundef %1) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !20, metadata !DIExpression()), !dbg !22
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !21, metadata !DIExpression()), !dbg !22
  ret void, !dbg !23
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { mustprogress nofree norecurse nosync nounwind willreturn memory(none) uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!6, !7, !8, !9, !10, !11, !12}
!llvm.ident = !{!13}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/infeasible_path.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "e53dd3b58e3f70d02a3b6141baab4488")
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
!14 = distinct !DISubprogram(name: "infeasible_path", scope: !15, file: !15, line: 3, type: !16, scopeLine: 4, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !19)
!15 = !DIFile(filename: "qa/tests/fixtures/infeasible_path.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "e53dd3b58e3f70d02a3b6141baab4488")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18, !5}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !{!20, !21}
!20 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 3, type: !18)
!21 = !DILocalVariable(name: "enabled", arg: 2, scope: !14, file: !15, line: 3, type: !5)
!22 = !DILocation(line: 0, scope: !14)
!23 = !DILocation(line: 9, column: 1, scope: !14)
