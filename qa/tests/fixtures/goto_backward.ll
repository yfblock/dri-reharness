; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/goto_backward.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/goto_backward.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @goto_backward(ptr noundef %0, i32 noundef %1) local_unnamed_addr #0 !dbg !14 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !20, metadata !DIExpression()), !dbg !23
  tail call void @llvm.dbg.value(metadata i32 %1, metadata !21, metadata !DIExpression()), !dbg !23
  %3 = getelementptr inbounds i8, ptr %0, i64 24
  %4 = icmp eq i32 %1, 0
  br label %5, !dbg !24

5:                                                ; preds = %5, %2
  call void @llvm.dbg.label(metadata !22), !dbg !25
  call void @llvm.dbg.value(metadata i32 1, metadata !26, metadata !DIExpression()), !dbg !35
  call void @llvm.dbg.value(metadata ptr %3, metadata !34, metadata !DIExpression()), !dbg !35
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 1, ptr nonnull elementtype(i32) %3) #3, !dbg !37, !srcloc !38
  br i1 %4, label %6, label %5, !dbg !39

6:                                                ; preds = %5
  ret void, !dbg !40
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
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/goto_backward.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "e3ff5c14adc52f0f3c47a08afdbce7b9")
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
!14 = distinct !DISubprogram(name: "goto_backward", scope: !15, file: !15, line: 5, type: !16, scopeLine: 6, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !19)
!15 = !DIFile(filename: "qa/tests/fixtures/goto_backward.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "e3ff5c14adc52f0f3c47a08afdbce7b9")
!16 = !DISubroutineType(types: !17)
!17 = !{null, !18, !5}
!18 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!19 = !{!20, !21, !22}
!20 = !DILocalVariable(name: "base", arg: 1, scope: !14, file: !15, line: 5, type: !18)
!21 = !DILocalVariable(name: "again", arg: 2, scope: !14, file: !15, line: 5, type: !5)
!22 = !DILabel(scope: !14, name: "err_retry", file: !15, line: 7)
!23 = !DILocation(line: 0, scope: !14)
!24 = !DILocation(line: 6, column: 1, scope: !14)
!25 = !DILocation(line: 7, column: 1, scope: !14)
!26 = !DILocalVariable(name: "val", arg: 1, scope: !27, file: !28, line: 67, type: !5)
!27 = distinct !DISubprogram(name: "writel", scope: !28, file: !28, line: 67, type: !29, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !33)
!28 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!29 = !DISubroutineType(types: !30)
!30 = !{null, !5, !31}
!31 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !32, size: 64)
!32 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!33 = !{!26, !34}
!34 = !DILocalVariable(name: "addr", arg: 2, scope: !27, file: !28, line: 67, type: !31)
!35 = !DILocation(line: 0, scope: !27, inlinedAt: !36)
!36 = distinct !DILocation(line: 8, column: 2, scope: !14)
!37 = !DILocation(line: 67, column: 1, scope: !27, inlinedAt: !36)
!38 = !{i64 2149613650}
!39 = !DILocation(line: 9, column: 6, scope: !14)
!40 = !DILocation(line: 11, column: 1, scope: !14)
