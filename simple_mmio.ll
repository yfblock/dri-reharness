; ModuleID = '/tmp/simple_mmio.c'
source_filename = "/tmp/simple_mmio.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

@reg_base = dso_local local_unnamed_addr global ptr null, align 8, !dbg !0

; Function Attrs: nofree norecurse nounwind uwtable
define dso_local void @enable() local_unnamed_addr #0 !dbg !21 {
  %1 = load ptr, ptr @reg_base, align 8, !dbg !26, !tbaa !27
  %2 = getelementptr inbounds i32, ptr %1, i64 8, !dbg !26
  store volatile i32 1, ptr %2, align 4, !dbg !31, !tbaa !32
  %3 = getelementptr inbounds i32, ptr %1, i64 9, !dbg !34
  %4 = load volatile i32, ptr %3, align 4, !dbg !34, !tbaa !32
  tail call void @llvm.dbg.value(metadata i32 %4, metadata !25, metadata !DIExpression()), !dbg !35
  %5 = or i32 %4, 256, !dbg !36
  %6 = getelementptr inbounds i32, ptr %1, i64 10, !dbg !37
  store volatile i32 %5, ptr %6, align 4, !dbg !38, !tbaa !32
  ret void, !dbg !39
}

; Function Attrs: nofree norecurse nounwind uwtable
define dso_local void @burst() local_unnamed_addr #0 !dbg !40 {
  tail call void @llvm.dbg.value(metadata i32 0, metadata !42, metadata !DIExpression()), !dbg !45
  %1 = load ptr, ptr @reg_base, align 8, !tbaa !27
  tail call void @llvm.dbg.value(metadata i32 0, metadata !42, metadata !DIExpression()), !dbg !45
  br label %3, !dbg !46

2:                                                ; preds = %3
  ret void, !dbg !47

3:                                                ; preds = %0, %3
  %4 = phi i64 [ 0, %0 ], [ %9, %3 ]
  tail call void @llvm.dbg.value(metadata i64 %4, metadata !42, metadata !DIExpression()), !dbg !45
  %5 = or disjoint i64 %4, 12, !dbg !48
  %6 = getelementptr inbounds i32, ptr %1, i64 %5, !dbg !50
  %7 = trunc i64 %4 to i32, !dbg !51
  %8 = shl i32 %7, 4, !dbg !51
  store volatile i32 %8, ptr %6, align 4, !dbg !51, !tbaa !32
  %9 = add nuw nsw i64 %4, 1, !dbg !52
  tail call void @llvm.dbg.value(metadata i64 %9, metadata !42, metadata !DIExpression()), !dbg !45
  %10 = icmp eq i64 %9, 4, !dbg !53
  br i1 %10, label %2, label %3, !dbg !46, !llvm.loop !54
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { nofree norecurse nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }

!llvm.dbg.cu = !{!2}
!llvm.module.flags = !{!13, !14, !15, !16, !17, !18, !19}
!llvm.ident = !{!20}

!0 = !DIGlobalVariableExpression(var: !1, expr: !DIExpression())
!1 = distinct !DIGlobalVariable(name: "reg_base", scope: !2, file: !5, line: 3, type: !6, isLocal: false, isDefinition: true)
!2 = distinct !DICompileUnit(language: DW_LANG_C11, file: !3, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, globals: !4, splitDebugInlining: false, nameTableKind: None)
!3 = !DIFile(filename: "/tmp/simple_mmio.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "9d4883db5697b91e4da42a25d59f7fea")
!4 = !{!0}
!5 = !DIFile(filename: "/tmp/simple_mmio.c", directory: "", checksumkind: CSK_MD5, checksum: "9d4883db5697b91e4da42a25d59f7fea")
!6 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !7, size: 64)
!7 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !8)
!8 = !DIDerivedType(tag: DW_TAG_typedef, name: "uint32_t", file: !9, line: 26, baseType: !10)
!9 = !DIFile(filename: "/usr/include/x86_64-linux-gnu/bits/stdint-uintn.h", directory: "", checksumkind: CSK_MD5, checksum: "256fcabbefa27ca8cf5e6d37525e6e16")
!10 = !DIDerivedType(tag: DW_TAG_typedef, name: "__uint32_t", file: !11, line: 42, baseType: !12)
!11 = !DIFile(filename: "/usr/include/x86_64-linux-gnu/bits/types.h", directory: "", checksumkind: CSK_MD5, checksum: "e1865d9fe29fe1b5ced550b7ba458f9e")
!12 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!13 = !{i32 7, !"Dwarf Version", i32 5}
!14 = !{i32 2, !"Debug Info Version", i32 3}
!15 = !{i32 1, !"wchar_size", i32 4}
!16 = !{i32 8, !"PIC Level", i32 2}
!17 = !{i32 7, !"PIE Level", i32 2}
!18 = !{i32 7, !"uwtable", i32 2}
!19 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!20 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!21 = distinct !DISubprogram(name: "enable", scope: !5, file: !5, line: 5, type: !22, scopeLine: 5, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !2, retainedNodes: !24)
!22 = !DISubroutineType(types: !23)
!23 = !{null}
!24 = !{!25}
!25 = !DILocalVariable(name: "v", scope: !21, file: !5, line: 7, type: !8)
!26 = !DILocation(line: 6, column: 5, scope: !21)
!27 = !{!28, !28, i64 0}
!28 = !{!"any pointer", !29, i64 0}
!29 = !{!"omnipotent char", !30, i64 0}
!30 = !{!"Simple C/C++ TBAA"}
!31 = !DILocation(line: 6, column: 22, scope: !21)
!32 = !{!33, !33, i64 0}
!33 = !{!"int", !29, i64 0}
!34 = !DILocation(line: 7, column: 18, scope: !21)
!35 = !DILocation(line: 0, scope: !21)
!36 = !DILocation(line: 8, column: 26, scope: !21)
!37 = !DILocation(line: 8, column: 5, scope: !21)
!38 = !DILocation(line: 8, column: 22, scope: !21)
!39 = !DILocation(line: 9, column: 1, scope: !21)
!40 = distinct !DISubprogram(name: "burst", scope: !5, file: !5, line: 11, type: !22, scopeLine: 11, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !2, retainedNodes: !41)
!41 = !{!42}
!42 = !DILocalVariable(name: "i", scope: !43, file: !5, line: 12, type: !44)
!43 = distinct !DILexicalBlock(scope: !40, file: !5, line: 12, column: 5)
!44 = !DIBasicType(name: "int", size: 32, encoding: DW_ATE_signed)
!45 = !DILocation(line: 0, scope: !43)
!46 = !DILocation(line: 12, column: 5, scope: !43)
!47 = !DILocation(line: 14, column: 1, scope: !40)
!48 = !DILocation(line: 13, column: 25, scope: !49)
!49 = distinct !DILexicalBlock(scope: !43, file: !5, line: 12, column: 5)
!50 = !DILocation(line: 13, column: 9, scope: !49)
!51 = !DILocation(line: 13, column: 30, scope: !49)
!52 = !DILocation(line: 12, column: 29, scope: !49)
!53 = !DILocation(line: 12, column: 23, scope: !49)
!54 = distinct !{!54, !46, !55, !56, !57}
!55 = !DILocation(line: 13, column: 36, scope: !43)
!56 = !{!"llvm.loop.mustprogress"}
!57 = !{!"llvm.loop.unroll.disable"}
