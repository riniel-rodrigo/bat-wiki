Sub ProcessarVenda(totalCompra As Double, clienteAtivo As Boolean, isVIP As Boolean)
    If Not clienteAtivo Then Exit Sub
    desconto = 0
    If totalCompra >= 1000 Then desconto = desconto + 0.05
    If isVIP Then desconto = desconto + 0.1
    totalComDesconto = totalCompra * (1 - desconto)
End Sub
