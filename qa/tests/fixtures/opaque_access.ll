; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/opaque_access.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/opaque_access.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @opaque_access(ptr noundef %0) local_unnamed_addr #0 !dbg !10 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !18, metadata !DIExpression()), !dbg !20
  %2 = load volatile i32, ptr %0, align 4, !dbg !21, !tbaa !22
  tail call void @llvm.dbg.value(metadata i32 %2, metadata !19, metadata !DIExpression()), !dbg !20
  %3 = or i32 %2, 1, !dbg !26
  store volatile i32 %3, ptr %0, align 4, !dbg !27, !tbaa !22
  tail call void asm sideeffect "", "~{memory},~{dirflag},~{fpsr},~{flags}"() #2, !dbg !28, !srcloc !29
  ret void, !dbg !30
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #2 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!2, !3, !4, !5, !6, !7, !8}
!llvm.ident = !{!9}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/opaque_access.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "81bc34301ed7d0ab5f989e83ef56ba44")
!2 = !{i32 7, !"Dwarf Version", i32 5}
!3 = !{i32 2, !"Debug Info Version", i32 3}
!4 = !{i32 1, !"wchar_size", i32 4}
!5 = !{i32 8, !"PIC Level", i32 2}
!6 = !{i32 7, !"PIE Level", i32 2}
!7 = !{i32 7, !"uwtable", i32 2}
!8 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!9 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!10 = distinct !DISubprogram(name: "opaque_access", scope: !11, file: !11, line: 1, type: !12, scopeLine: 2, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !17)
!11 = !DIFile(filename: "qa/tests/fixtures/opaque_access.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "81bc34301ed7d0ab5f989e83ef56ba44")
!12 = !DISubroutineType(types: !13)
!13 = !{null, !14}
!14 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !15, size: 64)
!15 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !16)
!16 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!17 = !{!18, !19}
!18 = !DILocalVariable(name: "reg", arg: 1, scope: !10, file: !11, line: 1, type: !14)
!19 = !DILocalVariable(name: "value", scope: !10, file: !11, line: 3, type: !16)
!20 = !DILocation(line: 0, scope: !10)
!21 = !DILocation(line: 3, column: 23, scope: !10)
!22 = !{!23, !23, i64 0}
!23 = !{!"int", !24, i64 0}
!24 = !{!"omnipotent char", !25, i64 0}
!25 = !{!"Simple C/C++ TBAA"}
!26 = !DILocation(line: 5, column: 15, scope: !10)
!27 = !DILocation(line: 5, column: 7, scope: !10)
!28 = !DILocation(line: 6, column: 2, scope: !10)
!29 = !{i64 117}
!30 = !DILocation(line: 7, column: 1, scope: !10)
