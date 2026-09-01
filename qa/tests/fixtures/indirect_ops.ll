; ModuleID = '/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/indirect_ops.c'
source_filename = "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/indirect_ops.c"
target datalayout = "e-m:e-p270:32:32-p271:32:32-p272:64:64-i64:64-i128:128-f80:128-n8:16:32:64-S128"
target triple = "x86_64-pc-linux-gnu"

; Function Attrs: nounwind uwtable
define dso_local void @indirect_caller(ptr noundef %0) local_unnamed_addr #0 !dbg !30 {
  tail call void @llvm.dbg.value(metadata ptr %0, metadata !34, metadata !DIExpression()), !dbg !35
  call void @llvm.dbg.value(metadata ptr %0, metadata !36, metadata !DIExpression()), !dbg !40
  call void @llvm.dbg.value(metadata i32 7, metadata !39, metadata !DIExpression()), !dbg !40
  %2 = getelementptr inbounds i8, ptr %0, i64 24, !dbg !42
  call void @llvm.dbg.value(metadata i32 7, metadata !43, metadata !DIExpression()), !dbg !52
  call void @llvm.dbg.value(metadata ptr %2, metadata !51, metadata !DIExpression()), !dbg !52
  tail call void asm sideeffect "movl $0,$1", "r,*m,~{memory},~{dirflag},~{fpsr},~{flags}"(i32 7, ptr nonnull elementtype(i32) %2) #2, !dbg !54, !srcloc !55
  ret void, !dbg !56
}

; Function Attrs: nocallback nofree nosync nounwind speculatable willreturn memory(none)
declare void @llvm.dbg.value(metadata, metadata, metadata) #1

attributes #0 = { nounwind uwtable "min-legal-vector-width"="0" "no-trapping-math"="true" "stack-protector-buffer-size"="8" "target-cpu"="x86-64" "target-features"="+cmov,+cx8,+fxsr,+mmx,+sse,+sse2,+x87" "tune-cpu"="generic" }
attributes #1 = { nocallback nofree nosync nounwind speculatable willreturn memory(none) }
attributes #2 = { nounwind }

!llvm.dbg.cu = !{!0}
!llvm.module.flags = !{!22, !23, !24, !25, !26, !27, !28}
!llvm.ident = !{!29}

!0 = distinct !DICompileUnit(language: DW_LANG_C11, file: !1, producer: "Ubuntu clang version 18.1.3 (1ubuntu1)", isOptimized: true, runtimeVersion: 0, emissionKind: FullDebug, retainedTypes: !2, globals: !6, splitDebugInlining: false, nameTableKind: None)
!1 = !DIFile(filename: "/home/yfblock/Code/dri-trans-paper/reharness/qa/tests/fixtures/indirect_ops.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "125df85f12afe0d74958f6b51bc1881d")
!2 = !{!3}
!3 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !4, size: 64)
!4 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: !5)
!5 = !DIBasicType(name: "unsigned int", size: 32, encoding: DW_ATE_unsigned)
!6 = !{!7}
!7 = !DIGlobalVariableExpression(var: !8, expr: !DIExpression())
!8 = distinct !DIGlobalVariable(name: "local_ops", scope: !0, file: !9, line: 14, type: !10, isLocal: true, isDefinition: true)
!9 = !DIFile(filename: "qa/tests/fixtures/indirect_ops.c", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "125df85f12afe0d74958f6b51bc1881d")
!10 = !DIDerivedType(tag: DW_TAG_const_type, baseType: !11)
!11 = distinct !DICompositeType(tag: DW_TAG_structure_type, name: "indirect_ops", file: !9, line: 5, size: 64, elements: !12)
!12 = !{!13}
!13 = !DIDerivedType(tag: DW_TAG_member, name: "emit", scope: !11, file: !9, line: 6, baseType: !14, size: 64)
!14 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !15, size: 64)
!15 = !DISubroutineType(types: !16)
!16 = !{null, !17, !18}
!17 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: null, size: 64)
!18 = !DIDerivedType(tag: DW_TAG_typedef, name: "u32", file: !19, line: 21, baseType: !20)
!19 = !DIFile(filename: "vendor/linux/include/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "12ca7bdb629352cc4c9a492f86b435a7")
!20 = !DIDerivedType(tag: DW_TAG_typedef, name: "__u32", file: !21, line: 27, baseType: !5)
!21 = !DIFile(filename: "vendor/linux/include/uapi/asm-generic/int-ll64.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "f4d0ec5bcdd84e825a78a7add39d54dd")
!22 = !{i32 7, !"Dwarf Version", i32 5}
!23 = !{i32 2, !"Debug Info Version", i32 3}
!24 = !{i32 1, !"wchar_size", i32 4}
!25 = !{i32 8, !"PIC Level", i32 2}
!26 = !{i32 7, !"PIE Level", i32 2}
!27 = !{i32 7, !"uwtable", i32 2}
!28 = !{i32 7, !"debug-info-assignment-tracking", i1 true}
!29 = !{!"Ubuntu clang version 18.1.3 (1ubuntu1)"}
!30 = distinct !DISubprogram(name: "indirect_caller", scope: !9, file: !9, line: 18, type: !31, scopeLine: 19, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !33)
!31 = !DISubroutineType(types: !32)
!32 = !{null, !17}
!33 = !{!34}
!34 = !DILocalVariable(name: "base", arg: 1, scope: !30, file: !9, line: 18, type: !17)
!35 = !DILocation(line: 0, scope: !30)
!36 = !DILocalVariable(name: "base", arg: 1, scope: !37, file: !9, line: 9, type: !17)
!37 = distinct !DISubprogram(name: "indirect_emit", scope: !9, file: !9, line: 9, type: !15, scopeLine: 10, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !38)
!38 = !{!36, !39}
!39 = !DILocalVariable(name: "value", arg: 2, scope: !37, file: !9, line: 9, type: !18)
!40 = !DILocation(line: 0, scope: !37, inlinedAt: !41)
!41 = distinct !DILocation(line: 20, column: 2, scope: !30)
!42 = !DILocation(line: 11, column: 21, scope: !37, inlinedAt: !41)
!43 = !DILocalVariable(name: "val", arg: 1, scope: !44, file: !45, line: 67, type: !5)
!44 = distinct !DISubprogram(name: "writel", scope: !45, file: !45, line: 67, type: !46, scopeLine: 67, flags: DIFlagPrototyped | DIFlagAllCallsDescribed, spFlags: DISPFlagLocalToUnit | DISPFlagDefinition | DISPFlagOptimized, unit: !0, retainedNodes: !50)
!45 = !DIFile(filename: "vendor/linux/arch/x86/include/asm/io.h", directory: "/home/yfblock/Code/dri-trans-paper/reharness", checksumkind: CSK_MD5, checksum: "7255a33f32535fc68bd0d1cd99111699")
!46 = !DISubroutineType(types: !47)
!47 = !{null, !5, !48}
!48 = !DIDerivedType(tag: DW_TAG_pointer_type, baseType: !49, size: 64)
!49 = !DIDerivedType(tag: DW_TAG_volatile_type, baseType: null)
!50 = !{!43, !51}
!51 = !DILocalVariable(name: "addr", arg: 2, scope: !44, file: !45, line: 67, type: !48)
!52 = !DILocation(line: 0, scope: !44, inlinedAt: !53)
!53 = distinct !DILocation(line: 11, column: 2, scope: !37, inlinedAt: !41)
!54 = !DILocation(line: 67, column: 1, scope: !44, inlinedAt: !53)
!55 = !{i64 2149613834}
!56 = !DILocation(line: 21, column: 1, scope: !30)
